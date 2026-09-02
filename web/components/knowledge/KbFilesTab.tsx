"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getWebNavigation,
  knowledgeBaseFilePath,
  knowledgeBaseFilePreviewTextPath,
  type KnowledgeBaseFile,
  type WebNavigationSource,
} from "@/features/knowledge/api/files";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";
import KbDocumentList from "./KbDocumentList";
import KbFilePreview from "./KbFilePreview";
import WebNavigationTree from "./WebNavigationTree";

interface KbFilesTabProps {
  kb: KnowledgeBase;
  task?: TaskState;
}

/**
 * Master-detail view for the "Files" tab: list of raw documents on the
 * left, inline preview pane on the right. Both the parent KB list (in
 * `/knowledge-bases`) and this file list can be collapsed to icon-only strips
 * to reclaim horizontal space for the actual preview content.
 */
export default function KbFilesTab({ kb, task }: KbFilesTabProps) {
  const [selectedFile, setSelectedFile] = useState<KnowledgeBaseFile | null>(
    null,
  );
  const [navigationSources, setNavigationSources] = useState<
    WebNavigationSource[] | null
  >(null);
  const [navigationLoading, setNavigationLoading] = useState(true);
  const fileListPanel = useCollapsiblePanel("knowledge-file-list");

  // Bump refreshKey when the active create/upload task settles so newly
  // indexed files appear automatically.
  const taskExecuting = task?.executing === true;
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    if (!taskExecuting) {
      setRefreshKey((n) => n + 1);
    }
  }, [taskExecuting]);

  const loadNavigation = useCallback(
    async (force = false) => {
      try {
        setNavigationSources(await getWebNavigation(kb.name, { force }));
      } catch {
        // A KB without persisted web navigation still has a usable file tree.
        setNavigationSources([]);
      } finally {
        setNavigationLoading(false);
      }
    },
    [kb.name],
  );

  useEffect(() => {
    void loadNavigation(refreshKey > 0);
  }, [loadNavigation, refreshKey]);

  const previewSource = useMemo<FilePreviewSource | null>(() => {
    if (!selectedFile) return null;
    return {
      filename: selectedFile.name,
      mimeType: selectedFile.mime_type ?? undefined,
      url: knowledgeBaseFilePath(kb.name, selectedFile.name),
      extractedTextUrl: knowledgeBaseFilePreviewTextPath(
        kb.name,
        selectedFile.name,
      ),
      size: selectedFile.size,
      id: `${kb.name}/${selectedFile.name}`,
    };
  }, [kb.name, selectedFile]);

  const selectNavigationFile = useCallback((filePath: string) => {
    setSelectedFile({ name: filePath, type: "file" });
  }, []);

  return (
    <div className="flex h-full min-h-0">
      {navigationSources?.length ? (
        <WebNavigationTree
          sources={navigationSources}
          loading={navigationLoading}
          selectedFile={selectedFile?.name ?? null}
          onSelect={selectNavigationFile}
          collapsed={fileListPanel.collapsed}
          onToggleCollapsed={fileListPanel.toggle}
          onRefresh={() => void loadNavigation(true)}
        />
      ) : (
        <KbDocumentList
          kbName={kb.name}
          refreshKey={refreshKey}
          selectedFile={selectedFile?.name ?? null}
          onSelect={setSelectedFile}
          collapsed={fileListPanel.collapsed}
          onToggleCollapsed={fileListPanel.toggle}
        />
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <KbFilePreview
          source={previewSource}
          fileListCollapsed={fileListPanel.collapsed}
          onToggleFileList={fileListPanel.toggle}
        />
      </div>
    </div>
  );
}
