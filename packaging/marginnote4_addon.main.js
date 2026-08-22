JSB.require("runtime");
JSB.require("mnutils");
JSB.require("mnnote");
JSB.require("network");

var DT_BATCH_SIZE = 200;
var DT_MAX_BACKOFF = 300;

function dtValue(value, fallback) {
  return value === null || value === undefined ? fallback : value;
}

function dtText(value) {
  return String(dtValue(value, ""));
}

function dtSeconds(date) {
  if (!date) return 0;
  try {
    return Math.floor(date.timeIntervalSince1970());
  } catch (error) {
    return 0;
  }
}

function dtIso(date) {
  var seconds = dtSeconds(date);
  if (!seconds) return "";
  return new Date(seconds * 1000).toISOString();
}

function dtIds(items) {
  var out = [];
  items = dtValue(items, []);
  for (var i = 0; i < items.length; i++) {
    if (items[i] && items[i].noteId) out.push(dtText(items[i].noteId));
  }
  return out;
}

function dtHash(text) {
  text = dtText(text);
  var hash = 5381;
  for (var i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) & 0x7fffffff;
  }
  return String(hash);
}

function dtBatchId(prefix) {
  return prefix + "-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
}

JSB.newAddon = function(mainPath) {
  Runtime.init(mainPath);
  Locale.init(mainPath);
  MNUtil.init(mainPath);

  return JSB.defineClass(
    "DeepTutorMarginNote4 : JSExtension",
    {
      sceneWillConnect: function() {
        this.syncing = false;
        this.fullResyncRequested = false;
        this.initLocalDatabase();
      },

      sceneDidBecomeActive: function() {
        this.syncIfNeeded();
      },

      applicationWillEnterForeground: function() {
        this.syncIfNeeded();
      },

      queryAddonCommandStatus: function() {
        return {
          image: "deeptutor.png",
          object: this,
          selector: "controlDeepTutor:",
          checked: false
        };
      },

      controlDeepTutor: function(sender) {
        JSB.log("DTMN4 command tapped");
        var clipboard = "";
        try {
          clipboard = dtText(UIPasteboard.generalPasteboard().string).trim();
        } catch (error) {
          JSB.log("DTMN4 clipboard read failed: %s", error);
        }
        if (clipboard === "DeepTutor full resync") {
          this.fullResyncRequested = true;
          UIPasteboard.generalPasteboard().string = "";
        } else if (clipboard === "DeepTutor revoke") {
          this.revokeLocalDevice();
          return;
        }
        this.syncIfNeeded(true);
      },

      initLocalDatabase: function() {
        var db = this.openDatabase(true);
        db.executeStatements(
          "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);" +
            "CREATE TABLE IF NOT EXISTS seen_objects (" +
            "object_id TEXT PRIMARY KEY, object_hash TEXT NOT NULL);"
        );
        db.close();
      },

      databasePath: function() {
        return NSHomeDirectory() + "/Documents/DeepTutorMN4-state.db";
      },

      openDatabase: function(createDirectory) {
        var path = this.databasePath();
        var db = SQLiteDatabase.databaseWithPath(path);
        db.open();
        return db;
      },

      config: function(key) {
        var db = this.openDatabase(false);
        var result = null;
        var cursor = db.executeQueryWithArgumentsInArray(
          "SELECT value FROM config WHERE key = ?",
          [key]
        );
        if (cursor.next()) result = cursor.stringForColumn("value");
        cursor.close();
        db.close();
        return result;
      },

      setConfig: function(key, value) {
        var db = this.openDatabase(false);
        db.executeUpdateWithArgumentsInArray(
          "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
          [key, String(value)]
        );
        db.close();
      },

      clearLocalState: function() {
        var db = this.openDatabase(false);
        db.executeStatements("DELETE FROM config; DELETE FROM seen_objects;");
        db.close();
      },

      revokeLocalDevice: function() {
        this.clearLocalState();
        Application.sharedInstance().alert("DeepTutor local credentials removed. Revoke the device in DeepTutor as well.");
      },

      syncIfNeeded: function(force) {
        if (this.syncing) return;
        var now = Math.floor(Date.now() / 1000);
        var nextAttempt = Number(this.config("next_attempt") || 0);
        if (!force && now < nextAttempt) return;

        var token = this.config("token");
        if (!token) {
          this.pairDevice();
          return;
        }

        var self = this;
        this.syncing = true;
        Application.sharedInstance().waitHUD("DeepTutor syncing...", this.window);
        this.runSync()
          .then(function(count) {
            self.setConfig("failure_count", "0");
            self.setConfig("next_attempt", "0");
            Application.sharedInstance().stopWaitHUDOnView(self.window);
            Application.sharedInstance().showHUD(
              "DeepTutor synced " + count + " objects",
              self.window,
              2
            );
            self.syncing = false;
          })
          .catch(function(error) {
            self.recordFailure(error);
            Application.sharedInstance().stopWaitHUDOnView(self.window);
            Application.sharedInstance().alert("DeepTutor sync failed: " + error);
            self.syncing = false;
          });
      },

      parsePairingText: function(text) {
        var parts = dtText(text).trim().split("|");
        if (parts.length !== 2) return null;
        var server = parts[0].replace(/\/+$/, "");
        var code = parts[1].trim();
        if (!/^https?:\/\/[^\s|]+$/i.test(server) || !/^[^\s|]+$/.test(code)) return null;
        return { server: server, code: code };
      },

      pairDevice: function() {
        var clipboard = "";
        try {
          clipboard = dtText(UIPasteboard.generalPasteboard().string).trim();
        } catch (error) {
          JSB.log("DTMN4 clipboard read failed: %s", error);
        }
        var existingPairing = this.parsePairingText(clipboard);
        try {
          this.showPairPanel(existingPairing ? existingPairing.server + "|" + existingPairing.code : "");
        } catch (error) {
          JSB.log("DTMN4 pair panel failed: %s", error);
          Application.sharedInstance().alert("DeepTutor pairing UI failed: " + error);
        }
      },

      claimDevice: function(pairing) {
        var self = this;
        var server = pairing.server;
        deepTutorFetch(server + "/api/v1/marginnote4/pair/claim", {
          method: "POST",
          json: {
            code: pairing.code,
            device_name: "MarginNote 4",
            device_kind: "macos",
            protocol_version: 1
          }
        })
          .then(function(response) {
            if (response.status >= 400) throw "pairing failed (" + response.status + ")";
            var payload = response.json();
            self.setConfig("server", server);
            self.setConfig("token", payload.token);
            self.setConfig("device_id", payload.device_id);
            self.fullResyncRequested = true;
            UIPasteboard.generalPasteboard().string = "";
            Application.sharedInstance().showHUD("DeepTutor paired", self.window, 2);
            self.syncIfNeeded(true);
          })
          .catch(function(error) {
            Application.sharedInstance().alert("DeepTutor pairing failed: " + error);
          });
      },

      frame: function(x, y, width, height) {
        return { x: x, y: y, width: width, height: height };
      },

      labelWithTitleFrame: function(title, frame, bold, color) {
        var label = new UILabel();
        label.frame = frame;
        label.text = title;
        label.font = bold ? UIFont.boldSystemFontOfSize(15) : UIFont.systemFontOfSize(13);
        label.textColor = color;
        label.numberOfLines = 0;
        return label;
      },

      showPairPanel: function(initialValue) {
        if (this.pairPanel) {
          if (this.pairHostView) this.pairHostView.bringSubviewToFront(this.pairOverlay);
          return;
        }

        var app = Application.sharedInstance();
        var studyController = app.studyController(this.window);
        var hostView = studyController ? studyController.view : null;
        if (!hostView) {
          app.alert("Open a MarginNote study window first, then tap the DeepTutor command.");
          return;
        }

        var bounds = hostView.bounds;
        var width = Math.min(440, Math.max(280, bounds.width - 48));
        var height = 208;
        var x = (bounds.width - width) / 2;
        var y = Math.max(24, (bounds.height - height) / 2);

        var overlay = new UIView(bounds);
        overlay.backgroundColor = UIColor.colorWithHexString("#111827").colorWithAlphaComponent(0.28);

        var panel = new UIView(this.frame(x, y, width, height));
        panel.backgroundColor = UIColor.colorWithHexString("#f8fafc");
        panel.layer.cornerRadius = 8;
        panel.layer.masksToBounds = true;

        var titleColor = UIColor.colorWithHexString("#0f172a");
        var messageColor = UIColor.colorWithHexString("#475569");
        var titleLabel = this.labelWithTitleFrame(
          "Connect DeepTutor",
          this.frame(24, 20, width - 48, 24),
          true,
          titleColor
        );
        var messageLabel = this.labelWithTitleFrame(
          "Paste https://host|pairing-code",
          this.frame(24, 50, width - 48, 20),
          false,
          messageColor
        );
        panel.addSubview(titleLabel);
        panel.addSubview(messageLabel);

        var input = new UITextField(this.frame(24, 82, width - 48, 36));
        input.backgroundColor = UIColor.colorWithHexString("#ffffff");
        input.textColor = titleColor;
        input.placeholder = "https://your-deeptutor-host|pairing-code";
        input.font = UIFont.systemFontOfSize(14);
        input.textAlignment = 0;
        input.borderStyle = 0;
        input.layer.cornerRadius = 6;
        input.layer.masksToBounds = true;
        input.text = dtText(initialValue);
        panel.addSubview(input);

        var cancelButton = UIButton.buttonWithType(0);
        cancelButton.frame = this.frame(24, 138, 96, 36);
        cancelButton.setTitleForState("Cancel", 0);
        cancelButton.setTitleColorForState(UIColor.colorWithHexString("#334155"), 0);
        cancelButton.backgroundColor = UIColor.colorWithHexString("#e2e8f0");
        cancelButton.layer.cornerRadius = 6;
        cancelButton.layer.masksToBounds = true;
        cancelButton.addTargetActionForControlEvents(this, "closePairPanel:", 1 << 6);
        panel.addSubview(cancelButton);

        var pairButton = UIButton.buttonWithType(0);
        pairButton.frame = this.frame(width - 120, 138, 96, 36);
        pairButton.setTitleForState("Pair", 0);
        pairButton.setTitleColorForState(UIColor.whiteColor(), 0);
        pairButton.backgroundColor = UIColor.colorWithHexString("#1d4ed8");
        pairButton.layer.cornerRadius = 6;
        pairButton.layer.masksToBounds = true;
        pairButton.addTargetActionForControlEvents(this, "confirmPairPanel:", 1 << 6);
        panel.addSubview(pairButton);

        overlay.addSubview(panel);
        hostView.addSubview(overlay);
        this.pairHostView = hostView;
        this.pairOverlay = overlay;
        this.pairPanel = panel;
        this.pairInput = input;
        this.pairMessageLabel = messageLabel;
      },

      closePairPanel: function(sender) {
        if (!this.pairOverlay) return;
        this.pairOverlay.removeFromSuperview();
        this.pairHostView = null;
        this.pairOverlay = null;
        this.pairPanel = null;
        this.pairInput = null;
        this.pairMessageLabel = null;
      },

      confirmPairPanel: function(sender) {
        if (!this.pairInput) return;
        var pairing = this.parsePairingText(this.pairInput.text);
        if (!pairing) {
          this.pairMessageLabel.textColor = UIColor.colorWithHexString("#dc2626");
          this.pairMessageLabel.text = "Use this format: https://host|pairing-code";
          return;
        }
        this.closePairPanel(sender);
        this.claimDevice(pairing);
      },

      recordFailure: function(error) {
        var failures = Number(this.config("failure_count") || 0) + 1;
        var delay = Math.min(DT_MAX_BACKOFF, Math.pow(2, failures));
        delay += Math.floor(Math.random() * Math.min(10, delay / 2));
        this.setConfig("failure_count", String(failures));
        this.setConfig(
          "next_attempt",
          String(Math.floor(Date.now() / 1000) + delay)
        );
        JSB.log(
          "DTMN4 retry scheduled failures=%d delay_seconds=%d",
          failures,
          delay
        );
      },

      runSync: function() {
        var objects = this.collectObjects();
        if (this.fullResyncRequested || !this.config("initialized")) {
          return this.runSnapshot(objects);
        }
        return this.runIncremental(objects);
      },

      collectObjects: function() {
        var objects = [];
        var documents = {};
        var rawDocuments = dtValue(MNUtil.allDocuments(), []);
        for (var i = 0; i < rawDocuments.length; i++) {
          var document = rawDocuments[i];
          documents[dtText(document.docMd5)] = document;
          objects.push({
            object_id: "document:" + dtText(document.docMd5),
            object_type: "document",
            title: dtText(document.docTitle),
            content: dtText(document.docTitle),
            document_id: dtText(document.docMd5),
            document_title: dtText(document.docTitle),
            revision: Math.max(1, dtSeconds(document.lastVisit)),
            created_at: dtIso(document.lastVisit),
            updated_at: dtIso(document.lastVisit),
            tags: [],
            links: [],
            raw: { path: dtText(document.fullPathFileName) }
          });
        }

        var notebooks = dtValue(MNUtil.allNotebooks(), []);
        for (var n = 0; n < notebooks.length; n++) {
          var notebook = notebooks[n];
          var tags = dtText(notebook.hashtags)
            .split(/[\s,]+/)
            .filter(function(tag) {
              return tag.length > 0;
            });
          var notes = dtValue(notebook.notes, []);
          for (var j = 0; j < notes.length; j++) {
            var note = notes[j];
            var noteId = dtText(note.noteId);
            var source = documents[dtText(note.docMd5)];
            var updated = Math.max(1, dtSeconds(note.modifiedDate));
            var title = dtText(note.noteTitle) || dtText(note.excerptText).slice(0, 120);
            objects.push({
              object_id: noteId,
              object_type: note.flashcard ? "card" : "mindmap_node",
              title: title,
              content: dtText(note.notesText) || title,
              excerpt: dtText(note.excerptText),
              document_id: dtText(note.docMd5),
              document_title: source ? dtText(source.docTitle) : "",
              page: note.startPage ? Number(note.startPage) + 1 : null,
              tags: tags,
              links: dtIds(note.linkedNotes)
                .concat(dtIds(note.childNotes))
                .concat(dtIds(note.summaryLinks)),
              color: note.colorIndex === null ? null : String(note.colorIndex),
              created_at: dtIso(note.createDate),
              updated_at: dtIso(note.modifiedDate),
              revision: updated,
              raw: {
                notebook_id: dtText(notebook.topicId),
                comment_count: dtValue(note.comments, []).length
              }
            });
          }
        }
        return objects;
      },

      objectHash: function(object) {
        return dtHash(
          [
            object.object_id,
            object.object_type,
            object.title,
            object.content,
            object.excerpt || "",
            object.revision
          ].join("\u001f")
        );
      },

      authorization: function() {
        return "Bearer MN4 " + this.config("token");
      },

      apiUrl: function(path) {
        return this.config("server") + path;
      },

      checkResponse: function(response, action) {
        if (response.status >= 400) {
          throw action + " failed (" + response.status + ")";
        }
        return response.json();
      },

      runSnapshot: function(objects) {
        var self = this;
        var total = Math.max(1, Math.ceil(objects.length / DT_BATCH_SIZE));
        var snapshotId = null;
        return deepTutorFetch(this.apiUrl("/api/v1/marginnote4/snapshots"), {
          method: "POST",
          authorization: this.authorization(),
          json: { protocol_version: 1, total_batches: total }
        })
          .then(function(response) {
            var payload = self.checkResponse(response, "snapshot create");
            snapshotId = payload.snapshot_id;
            return self.uploadSnapshotBatches(snapshotId, objects, total);
          })
          .then(function() {
            return deepTutorFetch(
              self.apiUrl("/api/v1/marginnote4/snapshots/" + snapshotId + "/commit"),
              { method: "POST", authorization: self.authorization() }
            );
          })
          .then(function(response) {
            var payload = self.checkResponse(response, "snapshot commit");
            self.setConfig("cursor", payload.cursor);
            self.setConfig("initialized", "1");
            self.fullResyncRequested = false;
            self.replaceSeenObjects(objects);
            return objects.length;
          });
      },

      uploadSnapshotBatches: function(snapshotId, objects, total) {
        var self = this;
        var sequence = 1;

        function uploadNext() {
          if (sequence > total) return Promise.resolve();
          var start = (sequence - 1) * DT_BATCH_SIZE;
          var batch = objects.slice(start, start + DT_BATCH_SIZE);
          return deepTutorFetch(
            self.apiUrl(
              "/api/v1/marginnote4/snapshots/" +
                snapshotId +
                "/batches/" +
                sequence
            ),
            {
              method: "PUT",
              authorization: self.authorization(),
              json: {
                protocol_version: 1,
                batch_id: dtBatchId("snapshot"),
                objects: batch
              }
            }
          ).then(function(response) {
            self.checkResponse(response, "snapshot batch " + sequence);
            sequence += 1;
            return uploadNext();
          });
        }

        return uploadNext();
      },

      runIncremental: function(objects) {
        var self = this;
        var previous = this.seenObjects();
        var changed = [];
        var nextSeen = {};

        for (var i = 0; i < objects.length; i++) {
          var object = objects[i];
          var hash = this.objectHash(object);
          nextSeen[object.object_id] = hash;
          if (previous[object.object_id] !== hash) changed.push(object);
        }

        var deleted = [];
        for (var id in previous) {
          if (!nextSeen[id]) deleted.push({ object_id: id, updated_at: "" });
        }
        if (!changed.length && !deleted.length) {
          return this.heartbeat().then(function() {
            return objects.length;
          });
        }

        var cursor = this.config("cursor") || "";
        var index = 0;

        function uploadNext() {
          if (index >= changed.length) return Promise.resolve();
          var batch = changed.slice(index, index + DT_BATCH_SIZE);
          index += batch.length;
          return deepTutorFetch(self.apiUrl("/api/v1/marginnote4/sync"), {
            method: "POST",
            authorization: self.authorization(),
            json: {
              protocol_version: 1,
              batch_id: dtBatchId("incremental"),
              cursor: cursor,
              objects: batch,
              deleted_objects: index >= changed.length ? deleted : []
            }
          }).then(function(response) {
            var payload = self.checkResponse(response, "incremental sync");
            cursor = payload.new_cursor;
            return uploadNext();
          });
        }

        return uploadNext()
          .then(function() {
            self.setConfig("cursor", cursor);
            self.replaceSeenObjects(objects);
            return changed.length + deleted.length;
          })
          .catch(function(error) {
            if (String(error).indexOf("failed (409)") >= 0) {
              self.fullResyncRequested = true;
              return self.runSnapshot(objects);
            }
            throw error;
          });
      },

      heartbeat: function() {
        return deepTutorFetch(this.apiUrl("/api/v1/marginnote4/heartbeat"), {
          method: "POST",
          authorization: this.authorization()
        }).then(function(response) {
          if (response.status >= 400) throw "heartbeat failed (" + response.status + ")";
          return response.json();
        });
      },

      seenObjects: function() {
        var db = this.openDatabase(false);
        var result = {};
        var cursor = db.executeQueryWithArgumentsInArray(
          "SELECT object_id, object_hash FROM seen_objects",
          []
        );
        while (cursor.next()) {
          result[cursor.stringForColumn("object_id")] = cursor.stringForColumn(
            "object_hash"
          );
        }
        cursor.close();
        db.close();
        return result;
      },

      replaceSeenObjects: function(objects) {
        var db = this.openDatabase(false);
        db.beginTransaction();
        db.executeUpdateWithArgumentsInArray("DELETE FROM seen_objects", []);
        for (var i = 0; i < objects.length; i++) {
          db.executeUpdateWithArgumentsInArray(
            "INSERT INTO seen_objects (object_id, object_hash) VALUES (?, ?)",
            [objects[i].object_id, this.objectHash(objects[i])]
          );
        }
        db.commit();
        db.close();
      }
    },
    {
      addonDidConnect: function() {},
      addonWillDisconnect: function() {},
      applicationDidEnterBackground: function() {},
      applicationDidReceiveLocalNotification: function() {}
    }
  );
};
