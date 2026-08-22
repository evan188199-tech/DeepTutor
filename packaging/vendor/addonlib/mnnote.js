class MNNote{
  static noteCache = {}
  /**
   * 
   * @param {string} message 
   * @param {any} detail 
   * @param {["INFO","ERROR","WARNING","DEBUG"]} level 
   */
  static log(message,detail,level = "INFO"){
    if (typeof MNLog !== "undefined") {
      MNLog.log({message:message,detail:detail,source:"MNNote",level:level})
      return
    }
    MNUtil.log({message:message,detail:detail,source:"MNNote",level:level})
  }
  /** @type {MbBookNote} */
  note
  /**
   * Initializes a new MNNote instance.
   * 
   * This constructor initializes a new MNNote instance based on the provided note object. The note object can be of various types:
   * - An MbBookNote instance.
   * - A string representing a note URL.
   * - A string representing a note ID.
   * - A configuration object for creating a new note.
   * 
   * If the note object is a string representing a note URL, the constructor will attempt to retrieve the corresponding note from the URL.
   * If the note object is a string representing a note ID, the constructor will attempt to retrieve the corresponding note from the database.
   * If the note object is a configuration object, the constructor will create a new note with the specified properties.
   * 
   * @param {MbBookNote|string|object} note - The note object to initialize the MNNote instance with.
   */
  constructor(note,type = undefined) {
  try {
    if (type === undefined) {
      type = MNUtil.typeOf(note)
    }
    switch (type) {
      case 'MbBookNote':
        this.note = note
        break;
      case 'NoteURL':
        let NoteFromURL = MNUtil.getNoteById(MNUtil.getNoteIdByURL(note))
        if (NoteFromURL) {
          this.note = NoteFromURL
        }
      case "NoteId":
      case 'string':
        let targetNoteId = note.trim()
        let targetNote = MNUtil.getNoteById(targetNoteId)
        if (targetNote) {
          this.note = targetNote
        }
        // MNUtil.showHUD(this.note.noteId)
        break;
        // MNUtil.copyJSON(targetNoteId+":"+this.note.noteId)
      case "NoteConfig":
        let config = note
        let notebook = MNUtil.currentNotebook
        let title = config.title ?? ""
        let content = config.excerptText ?? config.content ?? ""
        let markdown = config.excerptTextMarkdown ?? config.markdown ?? false
        // MNUtil.showHUD("new note")
        // MNUtil.copyJSON(note)
        this.note = Note.createWithTitleNotebookDocument(title, notebook, MNUtil.currentDocController.document)
        if (content.trim()) {//excerptText参数优先级高于content
          this.note.excerptText = content.trim()
          if (markdown) {
            this.note.excerptTextMarkdown = true
            if (/!\[.*?\]\((data:image\/.*;base64,.*?)(\))/.test(config.excerptText)) {
              this.note.processMarkdownBase64Images()
            }
          }
        }
        if (config.inCurrentChildMap) {
          if (this.currentChildMap) {
            let child = MNNote.currentChildMap.createChildNote(config)
            return child
          }
        }
        if (config.color !== undefined) {
          this.note.colorIndex = MNUtil.getColorIndex(config.color)
        }
        if (config.colorIndex !== undefined) {
          this.note.colorIndex = config.colorIndex
        }
        if ("tags" in config && config.tags.length) {
          this.note.appendTextComment(config.tags.map(k => '#'+k.replace(/\s+/g, "_")).join(" "))
        }
        if ("html" in config ) {
          note.appendHtmlComment(config.html, config.html, {width:1000,height:500}, "")
        }
        if ("parentNoteId" in config && config.parentNoteId) {
          let parentNote = MNNote.new(config.parentNoteId)
          if (parentNote) {
            this.note = parentNote.addAsChildNote(this.note)
          }
        }
        break;
      default:
        break;
    }
    
  } catch (error) {
    MNNote.addErrorLog(error, "MNNote.constructor")
  }
  }

  /**
   * Creates a new MNNote instance based on the provided note object.
   * 
   * This static method initializes a new MNNote instance based on the provided note object. The note object can be of various types:
   * - An MbBookNote instance.
   * - A string representing a note URL.
   * - A string representing a note ID.
   * - A configuration object for creating a new note.
   * 
   * If the note object is a string representing a note URL, the method will attempt to retrieve the corresponding note from the URL.
   * If the note object is a string representing a note ID, the method will attempt to retrieve the corresponding note from the database.
   * If the note object is a configuration object, the method will create a new note with the specified properties.
   * 
   * @param {MbBookNote|string|object} note - The note object to initialize the MNNote instance with.
   * @returns {MNNote|undefined} The initialized MNNote instance or undefined if the note object is invalid.
   */
  static new(note,alert = true){
    if (note === undefined) {
      return undefined
    }
    let noteId = undefined
    let noteType = MNUtil.typeOf(note)
    let newNote = undefined
    switch (noteType) {
      case "MNNote":
        return note;//原地返回
      case 'MbBookNote':
        return this.noteFromNote(note)
      case 'TocNoteURL':
      case 'NoteURL':
        noteId = MNUtil.getNoteIdByURL(note)
        return this.noteFromId(noteId)
      case "NoteId":
        return MNNote.noteFromId(note)
      case 'string':
        if (note === "current" || note === "currentNote" || note === "focused" || note === "focusedNote") {
          return MNNote.getFocusNote()
        }
        let targetNoteId = note.trim()
        return MNNote.noteFromId(targetNoteId)
      case "NoteConfig":
        let config = note
        if (!MNUtil.currentDocController.document) {
          MNUtil.confirm("No document in studyset!", "学习集中没有文档！")
          return undefined
        }
        newNote = new MNNote(config,"NoteConfig")
        this.noteCache[newNote.noteId] = newNote
        return newNote
      default:
        return undefined
    }
  }
  /**
   * 从缓存中获取note
   * @param {string} noteId 
   * @returns {MNNote|undefined}
   */
  static getNoteFromCache(noteId){
    if (noteId in this.noteCache) {
      return this.noteCache[noteId]
    }
    return undefined
  }
  /**
   * 统一处理缓存问题，如果noteId在缓存中，则返回缓存中的note，否则创建新的note并缓存
   * @param {string} noteId 
   * @returns {MNNote|undefined}
   */
  static noteFromId(noteId){
    try {
      if (noteId in this.noteCache) {
        let newNote = this.getNoteFromCache(noteId)
        return newNote
      }
      let newNote = new MNNote(noteId,"NoteId")
      this.noteCache[noteId] = newNote
      return newNote
    } catch (error) {
      MNNote.addErrorLog(error, "noteFromId", noteId)
      return undefined
    }
  }
  /**
   * 统一处理缓存问题，如果noteId在缓存中，则返回缓存中的note，否则创建新的note并缓存
   * @param {MbBookNote} note 
   * @returns {MNNote|undefined}
   */
  static noteFromNote(note){
    let noteId = note.noteId
    try {
      if (noteId in this.noteCache) {
        let newNote = this.getNoteFromCache(noteId)
        return newNote
      }
      let newNote = new MNNote(note,"MbBookNote")
      this.noteCache[noteId] = newNote
      return newNote
    } catch (error) {
      MNNote.addErrorLog(error, "noteFromNote", noteId)
      return undefined
    }
  }
  get noteId() {
    return this.note.noteId
  }
  get id(){
    return this.note.noteId
  }
  /**
   * 不考虑评论
   * @returns {string}
   */
  get type(){
    let type = "textNote"
    let isBlankNote = MNUtil.isBlankNote(this)
    if (isBlankNote) {
      type = "blankTextNote"
      return type
    }
    if (this.excerptPic) {
      if ("video" in this.excerptPic) {
        type = "videoNote"
        return type
      }
      if (!this.textFirst) {
        type = "imageNote"
        return type
      }
    }
    return type
  }
  get isBlankNote(){
    let excerptPic = this.note.excerptPic
    if (excerptPic) {
      let imageData = MNUtil.getMediaByHash(excerptPic.paint)
      return MNUtil.isEmptyImage(imageData)
    }
    return false
  }
  get notebookId() {
    return this.note.notebookId
  }
  get notebook(){
    return MNNotebook.new(this.notebookId)
  }
  /**
   * 文档摘录和它在脑图对应的卡片具有不同的id,通过originNoteId可以获得文档摘录的id
   * 
   * @returns {string} The original note ID of the merged note.
   */
  get originNoteId(){
    return this.note.originNoteId
  }
  /**
   * 文档摘录和它在脑图对应的卡片具有不同的id,通过originNoteId可以获得文档摘录的id
   * 
   * @returns {MNNote} The original note ID of the merged note.
   */
  get originNote(){
    return MNNote.new(this.note.originNoteId)
  }
  /**
   * Retrieves the note ID of the main note in a group of merged notes.
   * 
   * This method returns the note ID of the main note in a group of merged notes. This is useful for identifying the primary note in a set of combined notes.
   * 
   * @returns {string} The note ID of the main note in the group of merged notes.
   */
  get groupNoteId(){
    return this.note.groupNoteId
  }
  /**
   * @returns {MNNote|undefined} The group note of the current note.
   */
  get groupNote(){
    if (this.note.groupNoteId) {
      return MNNote.new(this.note.groupNoteId)
    }
    return undefined
  }
  get groupMode(){
    return this.note.groupMode
  }
  /**
   * @returns {string}
   */
  get getNoteColorHex(){
    return MNUtil.noteColorByNotebookIdAndColorIndex(this.notebookId,this.colorIndex)
    // let colorIndex = this.note.colorIndex
    // let theme = MNUtil.app.currentTheme
    // let colorConfig = {
    //   Default:["#ffffb4","#ccfdc4","#b4d1fb","#f3aebe","#ffff54","#75fb4c","#55bbf9","#ea3323","#ef8733","#377e47","#173dac","#be3223","#ffffff","#dadada","#b4b4b4","#bd9edc"],
    //   Dark:["#a0a071","#809f7b","#71839e","#986d77","#a0a032","#479e2c","#33759c","#921c12","#96551c","#204f2c","#0c266c","#771e14","#a0a0a0","#898989","#717171","#77638a"],
    //   Gary:["#d2d294","#a8d1a1","#94accf","#c88f9d","#d2d244","#5fcf3d","#459acd","#c0281b","#c46f28","#2c683a","#12328e","#9c281c","#d2d2d2","#b4b4b4","#949494","#9c82b5"]
    // }
    // let colorHexes = (theme in colorConfig)?colorConfig[theme]:colorConfig["Default"]
    // if (colorIndex !== undefined && colorIndex >= 0) {
    //   return colorHexes[colorIndex]
    // }
    // return "#ffffff"
  }
  /**
   * @returns {string}
   */
  get colorHex(){
    return MNUtil.noteColorByNotebookIdAndColorIndex(this.notebookId,this.colorIndex)
  }
  /**
   * @returns {boolean}
   * true: open
   * false: closed (对子脑图无效，依然为open)
   */
  get mindmapBranchClose(){
    return this.note.mindmapBranchClose
  }
  /**
   * Retrieves the child notes of the current note.
   * 
   * This method returns an array of MNNote instances representing the child notes of the current note. If the current note has no child notes, it returns an empty array.
   * 
   * @returns {MNNote[]} An array of MNNote instances representing the child notes.
   */
  get childNotes() {
    return this.note.childNotes?.map(k => new MNNote(k)) ?? []
  }
  /**
   * Retrieves the parent note of the current note.
   * 
   * This method returns an MNNote instance representing the parent note of the current note. If the current note has no parent note, it returns undefined.
   * 
   * @returns {MNNote|undefined} The parent note of the current note, or undefined if there is no parent note.
   */
  get parentNote() {
    return this.note.parentNote && new MNNote(this.note.parentNote)
  }
  get parentNoteId(){
    return this.note.parentNote?.noteId
  }
  /**
   * 
   * @param {MNNote|string|MbBookNote} note 
   */
  set parentNote(note){
    let parentNote = MNNote.new(note)
    parentNote.addAsChildNote(this)
  }
  /**
   * Retrieves the URL of the current note.
   * 
   * This method generates and returns the URL of the current note, which can be used to reference or share the note.
   * 
   * @returns {string} The URL of the current note.
   */
  get noteURL(){
    return MNUtil.version.version+'app://note/'+this.note.noteId
  }
  /**
   * Retrieves the URL of the current note.
   * 
   * This method generates and returns the URL of the current note, which can be used to reference or share the note.
   * 
   * @returns {string} The URL of the current note.
   */
  get url(){
    return MNUtil.version.version+'app://note/'+this.note.noteId
  }
  /**
   * Retrieves the child mind map note of the current note.
   * 
   * This method returns an MNNote instance representing the child mind map note of the current note. If the current note has no child mind map note, it returns undefined.
   * 
   * @returns {MNNote|undefined} The child mind map note of the current note, or undefined if there is no child mind map note.
   */
  get childMindMap(){
    if (this.note.childMindMap) {
      return MNNote.new(this.note.childMindMap)
    }
    return undefined
  }
  /**
   *
   * @returns {{descendant:MNNote[],treeIndex:number[][]}}
   */
  get descendantNodes() {
    const { childNotes } = this
    if (!childNotes.length) {
      return {
        descendant: [],
        treeIndex: []
      }
    } else {
      /**
       *
       * @param {MNNote[]} nodes
       * @param {number} level
       * @param {number[]} lastIndex
       * @param {{descendant:MNNote[],treeIndex:number[][]}} ret
       * @returns
       */
      function down(
        nodes,
        level = 0,
        lastIndex = [],
        ret = {
          descendant: [],
          treeIndex: []
        }
      ) {
        level++
        nodes.forEach((node, index) => {
          ret.descendant.push(node)
          lastIndex = lastIndex.slice(0, level - 1)
          lastIndex.push(index)
          ret.treeIndex.push(lastIndex)
          if (node.childNotes?.length) {
            down(node.childNotes, level, lastIndex, ret)
          }
        })
        return ret
      }
      return down(childNotes)
    }
  }
  get ancestorNodes() {
    /**
     *
     * @param {MNNote} node
     * @param {MNNote[]} ancestorNodes
     * @returns
     */
    function up(node, ancestorNodes) {
      if (node.note.parentNote) {
        const parentNode = new MNNote(node.note.parentNote)
        ancestorNodes = up(parentNode, [...ancestorNodes, parentNode])
      }
      return ancestorNodes
    }
    return up(this, [])
  }
  /**
   * Retrieves the notes associated with the current note.
   * 
   * This method returns an array of notes that are linked to the current note. It includes the current note itself and any notes that are linked through the comments.
   * 
   * @returns {MNNote[]} An array of MNNote instances representing the notes associated with the current note.
   */
  get notes() {
    return this.note.comments.reduce(
      (acc, cur) => {
        cur.type == "LinkNote" && MNUtil.noteExists(cur.noteid) && acc.push(MNNote.new(cur.noteid))
        return acc
      },
      [this]
    )
  }
  /**
   * Retrieves the titles associated with the current note.
   * 
   * This method splits the note title by semicolons and returns an array of unique titles. If the note title is not defined, it returns an empty array.
   * 
   * @returns {string[]} An array of unique titles associated with the current note.
   */
  get titles() {
    let titles = this.note.noteTitle?.split(/\s*[;；]\s*/) ?? []
    if (titles.length > 0) {
      return MNUtil.unique(titles, true)
    }
    return []
  }
  /**
   * Sets the titles associated with the current note.
   * 
   * This method sets the titles associated with the current note by joining the provided array of titles with semicolons. If the excerpt text of the note is the same as the note title, it updates both the note title and the excerpt text.
   * 
   * @param {string[]} titles - The array of titles to set for the current note.
   */
  set titles(titles) {
    if (typeof titles === "string") {
      //如果提供的不是数组，则与set title方法一致
      this.note.noteTitle = titles
      return
    }
    const newTitle = MNUtil.unique(titles, true).join("; ")
    if (this.note.excerptText === this.note.noteTitle) {
      this.note.noteTitle = newTitle
      this.note.excerptText = newTitle
    } else {
      this.note.noteTitle = newTitle
    }
  }

  /**
   * 卡片标题，但不包括markdown标题
   * @returns {string}
   */
  get title() {
    let titles = this.titlesWithoutMarkdownSource
    if (!titles || titles.length === 0) {
      return ""
    }
    return titles.join("; ")
  }
  /**
   *
   * @param {string} title
   * @returns
   */
  set title(title) {
    this.note.noteTitle = title
  }
  /**
   * 这里不去除markdown标题，保证兼容性
   * @returns {string}
   */
  get noteTitle() {
    return this.note.noteTitle ?? ""
  }
  /**
   *
   * @param {string} title
   * @returns
   */
  set noteTitle(title) {
    this.note.noteTitle = title
  }
  /**
   * 当卡片的内容为markdown时，其markdown标题会被添加进卡片标题，格式为{{title}}，这里需要将其提取出来
   * @returns {string[]}
   */
  get titlesFromMarkdown(){
  try {

    let titles = this.titles
    if (!titles || titles.length === 0) {
      return []
    }
    return titles.filter(t=>{
      if (/{{.*}}/.test(t)) {
        return true
      }
      return false
    })
    
  } catch (error) {
    MNNote.addErrorLog(error, "titlesFromMarkdown", this.noteId)
    return []
  }
  }
  /**
   * 当卡片的内容为markdown时，其markdown标题会被添加进卡片标题，格式为{{title}}，这里需要将其删除
   * @returns {string[]}
   */
  get titlesWithoutMarkdownSource(){
  try {

    let titles = this.titles
    if (!titles || titles.length === 0) {
      return []
    }
    return titles.filter(t=>{
      if (/{{.*}}/.test(t)) {
        return false
      }
      return true
    })
    
  } catch (error) {
    MNNote.addErrorLog(error, "titlesWithoutMarkdownSource", this.noteId)
    return []
  }
  }

  get isOCR() {
    let excerpt = this.excerpt
    if (excerpt.type === "text") {
      return excerpt.textFirst
    }
    return false
  }
  get excerptType(){
  try {
    let excerptPic = this.note.excerptPic
    if (excerptPic) {
      let possibleBlankNote = false
      if (excerptPic.selLst) {
        excerptPic.selLst.map(item=>{
          if (item.pageNo > 10000) {
            possibleBlankNote = true
          }
        })
      }
      if (possibleBlankNote && this.isBlankNote) {
        return "text"
      }
      if ("video" in excerptPic) {
        if (excerptPic.video_ext === "mp3") {
          return "audio"
        }
        return "video"
      }
      if (this.textFirst) {
        return "text"
      }
      return "image"
    }
    return "text"
    
  } catch (error) {
    MNNote.addErrorLog(error, "excerptType", this.noteId)
    return undefined
  }
  
  }
  _excerptCache = undefined
  getExcerptInfo(){
  try {
    let info = {}
    let excerptPic = this.note.excerptPic
    if (excerptPic) {
      if (excerptPic.paint) {
        info.imageHash = excerptPic.paint
      }
      if (excerptPic.size) {
        let size = MNUtil.NSValue2CGSize(excerptPic.size)
        info.size = size
      }
      let possibleBlankNote = false
      if (excerptPic.selLst) {
        let pageNos = []
        let selList = excerptPic.selLst.map(item=>{
          let rect = MNUtil.NSValue2CGRect(item.rect)
          let imgRect = MNUtil.NSValue2CGRect(item.imgRect)
          pageNos.push(item.pageNo)
          if (item.pageNo > 10000) {
            possibleBlankNote = true
          }
          return {
            rect: rect,
            imgRect: imgRect,
            pageNo: item.pageNo,
            rotation: item.rotation
          }
        })
        info.selList = selList
        info.pageNos = pageNos
      }
      if (possibleBlankNote && this.isBlankNote) {
        info.type = "text"
        info.text = this.note.excerptText
        info.textFirst = false
        info.isBlankNote = true
        return info
      }
      if ("video" in excerptPic) {
        if (excerptPic.video_ext === "mp3") {
          info.type = "audio"
          info.audioHash = excerptPic.video
          info.audioType = excerptPic.video_ext
          info.audioOffset = excerptPic.video_offset
          return info
        }
        info.type = "video"
        info.videoHash = excerptPic.video
        info.videoType = excerptPic.video_ext
        info.videoOffset = excerptPic.video_offset
        return info
      }
      if (this.textFirst) {
        info.type = "text"
        info.text = this.note.excerptText
        info.textFirst = true
        return info
      }
      info.type = "image"
      return info
    }
    info.type = "text"
    info.text = this.note.excerptText
    info.textFirst = false
    return info
    
  } catch (error) {
    MNNote.addErrorLog(error, "excerpt", this.noteId)
    return undefined
  }
  }
  /**
   * 获取卡片内容信息
   * @returns {{type:string,text:string,textFirst:boolean,isBlankNote:boolean,videoHash:string,videoType:string,videoOffset:number,audioHash:string,audioType:string,audioOffset:number,imageHash:string,size:CGSize,selList:CGRect[],pageNos:number[]}}
   */
  get excerpt(){
    if (this._excerptCache) {
      let refreshTime = this._excerptCache.refreshTime
      if (refreshTime && (Date.now() - refreshTime < 100)) {
        return this._excerptCache.info
      }
    }else{
      this._excerptCache = {}
    }
    this._excerptCache.info = this.getExcerptInfo()
    this._excerptCache.refreshTime = Date.now()
    return this._excerptCache.info
  }
  get textFirst() {
    let textFirst = this.note.textFirst
    if (textFirst === undefined) {
      textFirst = false
    }
    return textFirst
  }
  /**
   * set textFirst
   * @param {boolean} on
   * @returns
   */
  set textFirst(on){
    this.note.textFirst = on
  }
  get excerptText(){
    return this.note.excerptText
  }
  get excerptTextMarkdown(){
    return this.note.excerptTextMarkdown;
  }
  set excerptTextMarkdown(status){
    this.note.excerptTextMarkdown = status
  }
  set excerptText(text){
    this.note.excerptText = text
    if (this.excerptPic && !this.textFirst) {
      this.textFirst = true
    }
  }
  get mainExcerptText() {
    return this.note.excerptText ?? ""
  }
  /**
   *
   * @param {string} text
   * @returns
   */
  set mainExcerptText(text) {
    this.note.excerptText = text
  }
  get excerptPic(){
    let excerpt = this.excerpt
    let excerptPic = this.note.excerptPic
    if (!excerptPic) {
      return undefined
    }
    excerptPic.size = excerpt.size
    excerptPic.selList = excerpt.selList
    return excerptPic
  }
  get excerptPicData(){
    let excerpt = this.excerpt
    let imageData = MNUtil.getMediaByHash(excerpt.imageHash)
    return imageData
  }
  get excerptVideoData(){
    let excerpt = this.excerpt
    return MNUtil.getMediaByHash(excerpt.videoHash)
  }
  get excerptAudioData(){
    let excerpt = this.excerpt
    return MNUtil.getMediaByHash(excerpt.audioHash)
  }
  get colorIndex(){
    return this.note.colorIndex
  }
  set colorIndex(index){
    this.note.colorIndex = index
  }
  /**
   * @param {string} color
   */
  set color(color){
    let colors  = ["LightYellow", "LightGreen", "LightBlue", "LightRed","Yellow", "Green", "Blue", "Red", "Orange", "DarkGreen","DarkBlue", "DeepRed", "White", "LightGray","DarkGray", "Purple"]
    let index = colors.indexOf(color)
    if (index === -1) {
      return
    }
    this.note.colorIndex = index
    return
  }
  get color(){
    let index = this.colorIndex
    let colors  = ["LightYellow", "LightGreen", "LightBlue", "LightRed","Yellow", "Green", "Blue", "Red", "Orange", "DarkGreen","DarkBlue", "DeepRed", "White", "LightGray","DarkGray", "Purple"]
    if (index === -1) {
      return ""
    }
    return colors[index]
  }
  get fillIndex(){
    return this.note.fillIndex
  }
  set fillIndex(index){
    this.note.fillIndex = index
  }
  /**
   * @returns {string} The date when the note was created.
   */
  get createDate(){
    return this.note.createDate
  }
  /**
   * @returns {number} The date when the note was created.
   */
  get createDateNumber(){
    return Date.parse(this.note.createDate)
  }
  /**
   * @returns {string} The date when the note was last modified.
   */
  get modifiedDate(){
    return this.note.modifiedDate
  }
  /**
   * @returns {number} The date when the note was last modified.
   */
  get modifiedDateNumber(){
    return Date.parse(this.note.modifiedDate)
  }

  get linkedNotes(){
    return this.note.linkedNotes
  }
  get summaryLinks(){
    return this.note.summaryLinks
  }
  get mediaList(){
    return this.note.mediaList
  }
  get image(){//第一个图片
    let imageData = MNNote.getImageFromNote(this,true)
    let image = imageData?UIImage.imageWithData(imageData):undefined
    return image
  }
  get imageId(){
    return MNNote.getImageIdFromNote(this,true)
  }
  get imageData(){
    return MNNote.getImageFromNote(this,true)
  }
  get images(){//所有图片
    let imageDatas = MNNote.getImagesFromNote(this)
    let images = imageDatas?imageDatas.map(imageData=>UIImage.imageWithData(imageData)):undefined
    return images
  }
  get imageDatas(){//所有图片
    return MNNote.getImagesFromNote(this)
  }
  get hasVideo(){
    if (this.excerptPic && "video" in this.excerptPic) {
      return true
    }
    return false
  }
  get videoId(){
    if (this.excerptPic && "video" in this.excerptPic) {
      return this.excerptPic.video
    }
    return undefined
  }
  get videoData(){
    if (this.excerptPic && "video" in this.excerptPic) {
      return MNUtil.getMediaByHash(this.excerptPic.video)
    }
    return undefined
  }

  /**
   *
   * @returns {NoteComment[]}
   */
  get comments(){
    return this.note.comments
  }
  /**
   *
   * @returns {MNComment[]}
   */
  get MNComments(){
    return MNComment.from(this)
  }
  /**
   * get all tags, without '#'
   * @returns {string[]}
   */
  get tags() {
    try {
    // MNUtil.showHUD("length: "+this.note.comments.length)
    const tags = this.note.comments.reduce((acc, cur) => {
      // MNUtil.showHUD("cur.type")
      if (cur.type == "TextNote" && MNUtil._isTagComment_(cur)) {
        acc.push(...cur.text.split(/\s+/).filter(k => k.startsWith("#")))
      }
      return acc
    }, [])
    return tags.map(k => k.slice(1))
    } catch (error) {
      MNUtil.showHUD(error)
      return []
    }
  }
  /**
   * set tags, will remove all old tags
   *
   * @param {string[]} tags
   * @returns
   */
  set tags(tags) {
    this.tidyupTags()
    tags = MNUtil.unique(tags, true)
    const lastComment = this.note.comments[this.note.comments.length - 1]
    if (lastComment?.type == "TextNote" && lastComment.text.startsWith("#")) {
      this.note.removeCommentByIndex(this.note.comments.length - 1)
    }
    this.appendTextComments(tags.map(k => '#'+k).join(" "))
  }
  /**
   * @returns {{ocr:string[],html:string[],md:string[]}}
   */
  get excerptsTextPic() {
    return this.notes.reduce(
      (acc, cur) => {
        Object.entries(MNNote.getNoteExcerptTextPic(cur)).forEach(([k, v]) => {
          if (k in acc) acc[k].push(...v)
        })
        return acc
      },
      {
        ocr: [],
        html: [],
        md: []
      }
    )
  }
  /**
   * @returns {{html:string[],md:string[]}}
   */
  get commentsTextPic() {
    return this.note.comments.reduce(
      (acc, cur) => {
        if (cur.type === "PaintNote") {
          const imgs = MNNote.exportPic(cur)
          if (imgs)
            Object.entries(imgs).forEach(([k, v]) => {
              if (k in acc) acc[k].push(v)
            })
        } else if (cur.type == "TextNote" || cur.type == "HtmlNote") {
          const text = cur.text.trim()
          if (text && !text.includes("marginnote3app") && !text.startsWith("#"))
            Object.values(acc).map(k => k.push(text))
        }
        return acc
      },
      {
        html: [],
        md: []
      }
    )
  }
  /** @returns {string[]} */
 get excerptsText() {
    return this.notes.reduce((acc, note) => {
      const text = note.excerptText?.trim()
      if (text) {
        switch (note.type) {
          case "textNote":
          case "blankTextNote":
            acc.push(text)
            break;
          case "imageNote":
            break;
        
          default:
            break;
        }
      }
      return acc
    }, [])
  }
  /**
   * get all comment text
   * @returns {string[]}
   */
  get commentsText() {
    return this.note.comments.reduce((acc, cur) => {
      if (cur.type == "TextNote" || cur.type == "HtmlNote") {
        const text = cur.text.trim()
        if (text && !text.includes("marginnote3app") && !text.startsWith("#"))
          acc.push(text)
      }
      return acc
    }, [])
  }
  /**
   * get all text and pic note will be OCR or be transformed to base64
   */
  get allTextPic() {
    const retVal = MNNote.getNoteExcerptTextPic(this.note)
    this.note.comments.forEach(k => {
      if (k.type === "PaintNote") {
        const imgs = MNNote.exportPic(k)
        if (imgs)
          Object.entries(imgs).forEach(([k, v]) => {
            if (k in retVal) retVal[k].push(v)
          })
      } else if (k.type == "TextNote" || k.type == "HtmlNote") {
        const text = k.text.trim()
        if (text) Object.values(retVal).map(k => k.push(text))
      } else if (k.type == "LinkNote") {
        const note = MNUtil.db.getNoteById(k.noteid)
        if (note)
          Object.entries(MNNote.getNoteExcerptTextPic(note)).forEach(([k, v]) => {
            if (k in retVal) retVal[k].push(...v)
          })
      }
    })
    return {
      html: retVal.html.join("\n\n"),
      ocr: retVal.ocr.join("\n\n"),
      md: retVal.md.join("\n\n")
    }
  }
  /**
   * Get all text
   */
  get allText() {

    const { mainExcerptText } = this
    const retVal = []
    switch (this.type) {
      case "textNote":
      case "blankTextNote":
        retVal.push(mainExcerptText)
        break;
      case "imageNote":
        break;
      default:
        break;
    }
    this.note.comments.forEach(k => {
      if (k.type == "TextNote" || k.type == "HtmlNote") {
        const text = k.text.trim()
        if (text) retVal.push(text)
      } else if (k.type == "LinkNote") {
        const note = MNNote.new(k.noteid)
        if (note) {
          switch (note.type) {
            case "textNote":
            case "blankTextNote":
              retVal.push(note.excerptText)
              break;
            case "imageNote":
              break;
            default:
              break;
          }
        }else{
          if (k.q_htext) {
            retVal.push(k.q_htext)
          }
        }
      }
    })
    return retVal.join("\n\n")
  }
  /**
   * Get all text.
   */
  get excerptsCommentsText() {
    const { mainExcerptText } = this
    const retVal =
      mainExcerptText && (!this.note.excerptPic?.paint || this.isOCR)
        ? [mainExcerptText]
        : []
    this.note.comments.forEach(k => {
      if (k.type == "TextNote" || k.type == "HtmlNote") {
        const text = k.text.trim()
        if (text && !text.includes("marginnote3app") && !text.includes("marginnote4app") && !text.startsWith("#"))
          retVal.push(text)
      } else if (k.type == "LinkNote") {
        const note = MNUtil.db.getNoteById(k.noteid)
        const text = note?.excerptText?.trim()
        if (text && (!note?.excerptPic?.paint || this.isOCR)) retVal.push(text)
      }
    })
    return retVal
  }
  get docMd5(){
    if (this.note.docMd5) {
      return this.note.docMd5
    }
    return undefined
  }
  get startPage(){
    return this.note.startPage
  }
  get endPage(){
    return this.note.endPage
  }
  get pageNos(){
  try {
    let notes = this.notes
    let pageNos = []
    for (let i = 0; i < notes.length; i++) {
      const note = notes[i];
      let startPage = note.note.startPage
      let endPage = note.note.endPage
      if (startPage !== undefined) {
        pageNos.push(startPage)
      }
      if (endPage !== undefined && endPage > startPage) {
        for (let j = startPage + 1; j < endPage; j++) {
          pageNos.push(j)
        }
      }
    }
    let uniquePageNos = Array.from(new Set(pageNos))
    return uniquePageNos
    
  } catch (error) {
    this.addErrorLog(error, "getNoteRelatedPageNos")
    return []
  }
  }
  get document(){
    return MNDocument.new(this.note.docMd5)
  }
  get brotherNotes(){
    let parentNote = this.parentNote
    if (parentNote) {
      return parentNote.childNotes
    }
    return []
  }
  /**在同级卡片中的索引 */
  get indexInBrotherNotes(){
  try {
    let parentNote = this.parentNote
    if (parentNote) {
      let childNoteIds = parentNote.childNotes.map(note=>note.noteId)
      return childNoteIds.indexOf(this.noteId)
    }
    return -1
  } catch (error) {
   MNNote.addErrorLog(error, "indexInBrotherNotes")
   return -1
  }
  }

  /**
   * 笔记可能已经被删除
   * @param {string} noteId 
   * @returns {boolean}
   */
  get exist(){
    let noteId = this.note.noteId
    if (noteId && MNUtil.db.getNoteById(noteId)) {
      return true
    }
    return false
  }
  open(){
    MNUtil.openURL(this.noteURL)
  }
  appendExcerptText(text){
    this.excerptText = this.excerptText+"\n"+text
  }
  prependExcerptText(text){
    this.excerptText = text+"\n"+this.excerptText
  }
  copy(){
    let noteInfo = {
      id:this.noteId,
      title:this.title,
      excerptText:this.excerptText,
      docMd5:this.docMd5,
      notebookId:this.notebookId,
      noteURL:this.noteURL,
      MNComments:this.MNComments
    }
    if (this.tags && this.tags.length > 0) {
      noteInfo.tags = this.tags
    }
    MNUtil.copy(noteInfo)
  }
  config(opt={first:true}){
    return MNUtil.getNoteObject(this,opt)
  }
  /**
   * 当前卡片可能只是文档上的摘录，通过这个方法获取它在指定学习集下的卡片noteId
   * 与底层API不同的是，这里如果不提供nodebookid参数，则默认为当前学习集的nodebookid
   * @param {string} nodebookid
   * @returns {string}
   */
  realGroupNoteIdForTopicId(nodebookid = MNUtil.currentNotebookId){
    this.note.originNoteId
    return this.note.realGroupNoteIdForTopicId(nodebookid)
  };
  /**
   * 当前卡片可能只是文档上的摘录，通过这个方法获取它在指定学习集下的卡片noteId
   * 与底层API不同的是，这里如果不提供nodebookid参数，则默认为当前学习集的nodebookid
   * @param {string} nodebookid
   * @returns {MNNote}
   */
  realGroupNoteForTopicId(nodebookid = MNUtil.currentNotebookId){
    let noteId = this.note.realGroupNoteIdForTopicId(nodebookid)
    if (!noteId) {
      return this
    }
    return MNNote.new(noteId)
  };
  /**
   * 当前卡片可能只是文档上的摘录，通过这个方法获取它在指定学习集下的卡片noteId
   * 与底层API不同的是，这里如果不提供nodebookid参数，则默认为当前学习集的nodebookid
   * @param {string} nodebookid
   * @returns {MNNote}
   */
  noteInDocForTopicId(nodebookid = MNUtil.currentNotebookId){
    let noteId = this.note.realGroupNoteIdForTopicId(nodebookid)
    if (!noteId) {
      return this
    }
    return MNNote.new(noteId)
  };
  processMarkdownBase64Images(){
    this.note.processMarkdownBase64Images();
  }
  /**
   * 包括标题，正文，和评论内容
   * 不包括链接和标签
   * @returns {string}
   */
  allNoteText(){
    return this.note.allNoteText()
  }
  /**
   * 与title的set方法一致，但会返回自身，便于链式调用
   * @param {string} title 
   * @returns {MNNote}
   */
  setTitle(title){
    this.noteTitle = title
    return this
  }
  /**
   * 与titles的set方法一致，但会返回自身，便于链式调用
   * @param {string[]} titles 
   * @returns {MNNote}
   */
  setTtiles(titles){
    this.titles = titles
    return this
  }
  /**
   * 更新标题，从markdown中提取标题
   * @param {string|string[]} title
   * @returns {MNNote}
   */
  setTitleAndUpdateFromMarkdown(title){
    let titles = Array.isArray(title) ? title : title.split(";").map(t=>t.trim())
    let headingNames = MNUtil.headingNamesFromMarkdown(this.allNoteText())
    if (headingNames.length) {
      //去重
      let newTitles = headingNames.filter(h=>!titles.includes(h))
      this.noteTitle = title+";"+newTitles.map(h=>"{{"+h+"}}").join(";")
      return this
    }else{
      //直接更新标题
      this.noteTitle = title
      return this
    }
  }
  /**
   * 更新标题，从markdown中提取标题
   * @returns {MNNote}
   */
  updateTitleFromMarkdown(){
    let titles = this.titlesWithoutMarkdownSource
    let headingNames = MNUtil.headingNamesFromMarkdown(this._getMDContent())
    if (headingNames.length) {
      //去重
      let newTitles = headingNames.filter(h=>!titles.includes(h))
      this.noteTitle = this.title+";"+newTitles.map(h=>"{{"+h+"}}").join(";")
      return this
    }else{
      //不需要更新标题
      return this
    }
  }
  /**
   * 只提取markdown格式的内容，如markdown正文和markdown评论
   * @returns {string}
   */
  _getMDContent(){
    let allContent = []
    if (this.excerptText && this.excerptTextMarkdown) {
      allContent.push(this.excerptText)
    }
    let comments = this.comments
    if (!comments || comments.length === 0) {
      return allContent.join("\n\n")
    }
    for (let i = 0; i < comments.length; i++) {
      const comment = comments[i];
      switch (comment.type) {
        case "TextNote":
          if (comment.markdown) {
            allContent.push(comment.text)
          }
          break;
        case "LinkNote":
          //目前默认为markdown文字
          if (comment.q_hpic  && comment.q_hpic.paint) {
            let imageData = MNUtil.getMediaByHash(comment.q_hpic.paint)
            if (MNUtil.isEmptyImage(imageData)) {
              if (comment.q_htext) {
                allContent.push(comment.q_htext)
              }
            }
          }else{
            allContent.push(comment.q_htext)
          }
          break
        default:
          break;
      }
    }
    return allContent.join("\n\n")
  }
  /*
   * 将当前笔记转为markdown格式，主要是方便AI和editor
   * @param {boolean} withBase64 是否将图片转换为base64编码
   * @returns {string}
   */
  getMDContent(withBase64 = false){
    let note = this.realGroupNoteForTopicId()
try {
  let title = this.title.trim()
  if (title.trim() && !title.startsWith("#")) {
    title = "# "+title.trim()
  }
  let textFirst = note.textFirst
  let excerptText
  if (note.excerptPic && !textFirst) {
    if (withBase64) {
      excerptText = `[image](${MNUtil.getMediaByHash(note.excerptPic.paint).base64Encoding()})`
    }else{
      excerptText = ""
    }
  }else{
    excerptText = note.excerptText ?? ""
  }
  if (note.comments.length) {
    let comments = note.comments
    for (let i = 0; i < comments.length; i++) {
      const comment = comments[i];
      switch (comment.type) {
        case "TextNote":
          if (/^marginnote\dapp\:\/\//.test(comment.text)) {
            //do nothing
          }else{
            excerptText = excerptText+"\n"+comment.text
          }
          break;
        case "HtmlNote":
          excerptText = excerptText+"\n"+comment.text
          break
        case "LinkNote":
          if (withBase64 && comment.q_hpic  && comment.q_hpic.paint && !textFirst) {
            let imageData = MNUtil.getMediaByHash(comment.q_hpic.paint)
            let imageSize = UIImage.imageWithData(imageData).size
            if (imageSize.width === 1 && imageSize.height === 1) {
              if (comment.q_htext) {
                excerptText = excerptText+"\n"+comment.q_htext
              }
            }else{
              excerptText = excerptText+`\n[image](${imageData.base64Encoding()})`
            }
          }else{
            excerptText = excerptText+"\n"+comment.q_htext
          }
          break
        case "PaintNote":
          if (withBase64 && comment.paint){
            excerptText = excerptText+`\n[image](${MNUtil.getMediaByHash(comment.paint).base64Encoding()})`
          }
          break
        default:
          break;
      }
    }
  }
  // excerptText = (excerptText && excerptText.trim()) ? this.highlightEqualsContentReverse(excerptText) : ""
  let content = title+"\n"+excerptText
  return content
}catch(error){
  MNNote.addErrorLog(error, "MNNote.getMDContent", info)
  return ""
}
  }
  /*
   * 从markdown内容中提取链接
   * @param {boolean} onlyLinks 是否只返回链接
   * @returns {string[]}
   */
  getLinksInMarkdownContent(onlyLinks = false){
    let content = this._getMDContent()
    let links = MNUtil.extractMarkdownLinks(content)
    if (onlyLinks) {
      return links.map(link=>link.link)
    }
    return links
  }
  /*
   * 从markdown内容中提取MN链接,即marginnote4app://note/ 后面的链接
   * @param {boolean} onlyLinks 是否只返回链接
   * @returns {string[]}
   */
  getMNLinksInMarkdownContent(onlyLinks = false){
    let content = this._getMDContent()
    let links = MNUtil.extractMarkdownLinks(content)
    links = links.filter(link=>/^marginnote4app\:\/\/note\//.test(link.link))
    if (onlyLinks) {
      return links.map(link=>link.link)
    }
    return links
  }
  /**
   * 
   * @returns {MNNote}
   */
  paste(){
    this.note.paste()
    return this
  }

  /**
   * Merges the current note with another note.
   * 
   * This method merges the current note with another note. The note to be merged can be specified in various ways:
   * - An MbBookNote instance.
   * - An MNNote instance.
   * - A string representing a note URL.
   * - A string representing a note ID.
   * 
   * If the note to be merged is a string representing a note URL, the method will attempt to retrieve the corresponding note from the URL.
   * If the note to be merged is a string representing a note ID, the method will attempt to retrieve the corresponding note from the database.
   * 
   * @param {MbBookNote|MNNote|string} note - The note to be merged with the current note.
   * @returns {MNNote}
   */
  merge(note){
    switch (MNUtil.typeOf(note)) {
      case "MbBookNote":
        this.note.merge(note)
        break;
      case "MNNote":
        this.note.merge(note.note)
        break;
      case "NoteURL":
        let noteFromURL = MNUtil.getNoteById(MNUtil.getNoteIdByURL(note))
        if (noteFromURL) {
          this.note.merge(noteFromURL)
        }else{
          MNNote.addErrorLog("Note not exist!", "merge", note)
        }
      case "NoteId":
      case "string":
        let targetNote = MNUtil.getNoteById(note)
        if (targetNote) {
          this.note.merge(targetNote)
        }else{
          MNNote.addErrorLog("Note not exist!", "merge", note)
        }
        break
      default:
        break;
    }
    return this
  }
  /**
   * Remove from parent
   * 去除当前note的父关系(没用过不确定具体效果)
   * @returns {MNNote}
   */
  removeFromParent(){
    this.note.removeFromParent()
    return this
  }
  /**
   * beforeNote的参数为数字时,代表在指定序号前插入,0为第一个
   * 无论什么情况都返回自身
   * @param {MNNote|string} note//被移动的卡片，即使该卡片不是子卡片
   * @param {MNNote|string|number|undefined} beforeNote//参考对象，将会成为该卡片的兄弟卡片，并移动到该卡片的前方
   * @returns {MNNote}
   */
  insertChildBefore(note,beforeNote){
  try {
    let childNoteSize = this.childNotes.length
    if (childNoteSize === 0 || beforeNote === undefined) {
    //如果没有子卡片,也就无所谓插入顺序
    //如果没有提供beforeNote,则插入到最后
      this.addChild(note)
      return this
    }

    if (typeof beforeNote === "number") {
      //限制beforeNote的值,确保能取到笔记
      beforeNote = MNUtil.constrain(beforeNote, 0, childNoteSize-1)
      let targetNote = this.childNotes[beforeNote]
      let note0 = MNNote.new(note)
      this.note.insertChildBefore(note0.note,targetNote.note)
      return this
    }else{
      let note0 = MNNote.new(note)
      let note1 = MNNote.new(beforeNote)
      this.note.insertChildBefore(note0.note,note1.note)
      return this
    }
    
  } catch (error) {
    MNNote.addErrorLog(error, "MNNote.insertChildBefore")
    return this
  }
  }
  /**
   * afterNote的参数为数字时,代表在指定序号前插入,0为第一个
   * 无论什么情况都返回自身
   * @param {MNNote|string} note//被移动的卡片，即使该卡片不是子卡片
   * @param {MNNote|string|number|undefined} afterNote//参考对象，将会成为该卡片的兄弟卡片，并移动到该卡片的后方
   * @returns {MNNote}
   */
  insertChildAfter(note,afterNote){
  try {
    let childNoteSize = this.childNotes.length
    if (childNoteSize === 0 || afterNote === undefined) {
    //如果没有子卡片,也就无所谓插入顺序
    //如果没有提供afterNote,则插入到最后
      this.addChild(note)
      return this
    }

    if (typeof afterNote === "number") {
      //限制afterNote的值,确保能取到笔记
      afterNote = MNUtil.constrain(afterNote, 0, childNoteSize-1)
      if (afterNote === childNoteSize-1) {//如果是最后一个,则插入到最后
        this.addChild(note)
        return this
      }
      //插入到指定卡片的下一张卡片的前面
      let targetNote = this.childNotes[afterNote+1]
      let note0 = MNNote.new(note)
      this.note.insertChildBefore(note0.note,targetNote.note)
      return this
    }else{
      let temAfterNote = MNNote.new(afterNote)
      let childNoteIds = this.childNotes.map(note=>note.noteId)
      let noteIndex = childNoteIds.indexOf(temAfterNote.noteId)
      if (noteIndex === -1) {//afterNote不在子卡片中,插入到最后
        this.addChild(note)
        return this
      }
      if (noteIndex === childNoteSize-1) {//如果是最后一个,则插入到最后
        this.addChild(note)
        return this
      }
      //插入到指定卡片的下一张卡片的前面
      let note0 = MNNote.new(childNoteIds[noteIndex+1])
      let note1 = MNNote.new(note)
      this.note.insertChildBefore(note1.note,note0.note)
      return this
    }
    
  } catch (error) {
    MNNote.addErrorLog(error, "MNNote.insertChildAfter")
    return this
  }
  }
  /**
   * Deletes the current note, optionally including its descendant notes.
   * 
   * This method deletes the current note from the database. If the `withDescendant` parameter is set to `true`, it will also delete all descendant notes of the current note.
   * The deletion can be grouped within an undo operation if the `undoGrouping` parameter is set to `true`.
   * 
   * @param {boolean} [withDescendant=false] - Whether to delete the descendant notes along with the current note.
   */
  _delete(withDescendant = false){
    if (withDescendant) {
      MNUtil.db.deleteBookNoteTree(this.note.noteId)
    }else{
      let childNotes = this.childNotes
      let parentNote = this.parentNote
      for (let i = 0; i < childNotes.length; i++) {
        const childNote = childNotes[i];
        parentNote.addAsChildNote(childNote)
      }
      MNUtil.db.deleteBookNote(this.note.noteId)
    }
  }
  /**
   * Deletes the current note, optionally including its descendant notes.
   * 
   * This method deletes the current note from the database. If the `withDescendant` parameter is set to `true`, it will also delete all descendant notes of the current note.
   * The deletion can be grouped within an undo operation if the `undoGrouping` parameter is set to `true`.
   * 
   * @param {boolean} [withDescendant=false] - Whether to delete the descendant notes along with the current note.
   * @param {boolean} [undoGrouping=false] - Whether to group the deletion within an undo operation.
   */
  async delete(withDescendant = false,undoGrouping = false,needConfrim = false){
    if (needConfrim) {
      let confirm = await MNUtil.confirm("Delete Note", "Are you sure you want to delete this note?")
      if (!confirm) {
        return
      }
    }
    if (undoGrouping) {
      MNUtil.undoGrouping(()=>{
        this._delete(withDescendant)
      })
    }else{
      this._delete(withDescendant)
    }
  }
  /**
   * 移动卡片到目标卡片(成为目标卡片的子卡片)
   * 如果提供的是索引,则是移动到同级卡片的目标索引
   * @param {MNNote|MbBookNote|number} note 
   */
  moveTo(note){
    if (typeof note === "number") {
      let brotherNotes = this.brotherNotes
      if (note >= brotherNotes.length-1) {
        //移动到同级卡片的最后一个卡片
        this.parentNote.addChild(this)
        // this.moveAfter(brotherNotes[brotherNotes.length-1])
        return
      }
      //移动到n就是移动到n的前面
      this.moveBefore(note)
      return
    }
    if (note.notebookId !== this.notebookId) {
      MNNote.addErrorLog("Notes not in the same notebook", "moveTo")
      return
    }
    note.addChild(this.note)
  }
  /**
   * 对于同级卡片,移动到指定卡片前
   * 如果目标卡片和当前卡片不属于同一个父卡片,也会成为目标卡片的同级卡片
   * 不需要父卡片提前用addChild之类的先添加目标卡片
   * @param {MNNote|MbBookNote|number} note 
   */
  moveBefore(note){
    if (typeof note === "number") {
      let parentNote = this.parentNote
      parentNote.insertChildBefore(this, note)
      return
    }
    let targetNote = MNNote.new(note)
    let parentNote = targetNote.parentNote
    parentNote.insertChildBefore(this, targetNote)
  }
  /**
   * 对于同级卡片,移动到指定卡片后
   * 如果目标卡片和当前卡片不属于同一个父卡片,也会成为目标卡片的同级卡片
   * 不需要父卡片提前用addChild之类的先添加目标卡片
   * @param {MNNote|MbBookNote|number} note 
   */
  moveAfter(note){
    if (typeof note === "number") {
      let parentNote = this.parentNote
      parentNote.insertChildAfter(this, note)
      return
    }
    let targetNote = MNNote.new(note)
    let parentNote = targetNote.parentNote
    parentNote.insertChildAfter(this, targetNote)
  }
  /**
   * Adds a child note to the current note.
   * 
   * This method adds a child note to the current note. The child note can be specified as an MbBookNote instance, an MNNote instance, a note URL, or a note ID.
   * If the child note is specified as a note URL or a note ID, the method will attempt to retrieve the corresponding note from the database.
   * If the child note is specified as an MNNote instance, the method will add the underlying MbBookNote instance as a child.
   * 
   * @param {MbBookNote|MNNote|string} note - The child note to add to the current note.
   * @returns {MNNote} The current note.
   */
  addChild(note){
    try {
    //只有脑图中的卡片可以添加子节点，文档上的摘录不行，先转为脑图卡片
    let parentNote = this.realGroupNoteForTopicId()
    let temNote = MNNote.new(note)
    if (temNote) {
      //先转为脑图卡片
      temNote = temNote.realGroupNoteForTopicId()
      let notebookId = parentNote.notebookId
      // if (temNote.notebookId !== notebookId) {
      //   temNote = temNote.realGroupNoteForTopicId(notebookId)
      // }
      if (temNote.notebookId !== notebookId) {
        //不是同一个学习集
        MNUtil.showHUD("Not in the same notebook")
        return
      }
      //添加子节点
      parentNote.note.addChild(temNote.note)
    }
    return this
    } catch (error) {
      MNNote.addErrorLog(error, "addChild")
      return this
    }
  }
  /**
   * Adds a target note as a child note to the current note.
   * 
   * This method adds the specified target note as a child note to the current note. If the `colorInheritance` parameter is set to true, the target note will inherit the color of the current note.
   * The operation is wrapped within an undo grouping to allow for easy undo operations.
   * 
   * @param {MbBookNote|MNNote} targetNote - The note to be added as a child note.
   * @param {boolean} [colorInheritance=false] - Whether the target note should inherit the color of the current note.
   * @returns {MNNote} The current note.
   */
  addAsChildNote(targetNote,colorInheritance=false) {
    if (colorInheritance) {
      targetNote.colorIndex = this.note.colorIndex
    }
    this.addChild(targetNote)
    return this
  }
  /**
   * Adds the specified note as a sibling note to the current note.
   * 
   * This method adds the specified note as a sibling note to the current note. If the current note has no parent note, it displays a HUD message indicating that there is no parent note.
   * If the `colorInheritance` parameter is set to true, the color index of the target note is set to the color index of the current note.
   * 
   * @param {MbBookNote|MNNote} targetNote - The note to be added as a sibling.
   * @param {boolean} [colorInheritance=false] - Whether to inherit the color index from the current note.
   * @returns {MNNote} The current note.
   */
  addAsBrotherNote(targetNote,colorInheritance=false) {
    if (!this.note.parentNote) {
      MNUtil.showHUD("No parent note!")
      return
    }
    let parent = this.parentNote
    if (colorInheritance) {
      targetNote.colorIndex = this.note.colorIndex
    }
    parent.addChild(targetNote)
    return this
  }
  /**
   * Creates a child note for the current note based on the provided configuration.
   * 
   * This method creates a new child note for the current note using the specified configuration. If the current note is a document excerpt and not a mind map note,
   * it will create the child note under the corresponding mind map note in the current notebook. The method can optionally group the operation within an undo group.
   * 
   * @param {{title:String,excerptText:string,excerptTextMarkdown:boolean,content:string,markdown:boolean,color:number}} config - The configuration for the new child note.
   * @param {boolean} [undoGrouping=true] - Whether to group the operation within an undo group.
   * @returns {MNNote} The newly created child note.
   */
  createChildNote(config,undoGrouping=true) {
    let child
    //只有脑图中的卡片可以添加子节点，文档上的摘录不行
    // let note = this.realGroupNoteForTopicId()
    // let noteIdInMindmap = this.note.realGroupNoteIdForTopicId(MNUtil.currentNotebookId)
    // if (noteIdInMindmap && this.noteId !== noteIdInMindmap) {
    //   //对文档摘录添加子节点是无效的，需要对其脑图中的节点执行添加子节点
    //   note = MNNote.new(noteIdInMindmap)
    // }
    if (undoGrouping) {
      MNUtil.undoGrouping(()=>{
        try {
          child = MNNote.new(config)
          if (!child) {
            return
          }
          this.addChild(child)
        } catch (error) {
          MNNote.addErrorLog(error, "createChildNote")
        }
      })
    }else{
      try {
        child = MNNote.new(config)
        if (!child) {
          return undefined
        }
        this.addChild(child)
      } catch (error) {
        MNNote.addErrorLog(error, "createChildNote")
      }
    }
    return child
  }
  /**
   *
   * @param {{title:String,content:String,markdown:Boolean,color:Number}} config
   * @returns {MNNote}
   */
  createBrotherNote(config,undoGrouping=true) {
    let note = this.realGroupNoteForTopicId()
    // let noteIdInMindmap = this.note.realGroupNoteIdForTopicId(MNUtil.currentNotebookId)
    // if (noteIdInMindmap && this.noteId !== noteIdInMindmap) {
    //   //对文档摘录添加子节点是无效的，需要对其脑图中的节点执行添加子节点
    //   note = MNNote.new(noteIdInMindmap)
    // }
    if (!note.parentNote) {
      MNUtil.showHUD("No parent note!")
      return
    }
    let child
    let parent = note.parentNote
    if (undoGrouping) {
      MNUtil.undoGrouping(()=>{
        child = MNNote.new(config)
        parent.addChild(child)
      })
    }else{
      child = MNNote.new(config)
      parent.addChild(child)
    }
    return child
  }
  /**
   * 支持检测摘录图片,markdown摘录中的MN图片,图片评论,合并的图片摘录
   * @returns {boolean}
   */
  hasImage(checkTextFirst = true){
    let note = this
    if (note.excerptPic) {
      if (MNUtil.isBlankNote(note)) {
        let text = note.excerptText
        if (note.excerptTextMarkdown) {
          if (MNUtil.hasMNImages(text.trim())) {
            return true
          }
        }
      }else{
        if (checkTextFirst && note.textFirst) {
          //检查发现图片已经转为文本，因此略过
        }else{
          return true
        }
      }
    }else{
      let text = note.excerptText
      if (note.excerptTextMarkdown) {
        if (MNUtil.hasMNImages(text.trim())) {
          return true
        }
      }
    }
    if (note.comments.length) {
      let imageData = undefined
      for (let i = 0; i < note.comments.length; i++) {
        const comment = note.comments[i];
        if (comment.type === 'PaintNote' && comment.paint) {
          imageData = MNUtil.getMediaByHash(comment.paint)
          break
        }
        if (comment.type === "LinkNote" && comment.q_hpic && comment.q_hpic.paint) {
          imageData = MNUtil.getMediaByHash(comment.q_hpic.paint)
          break
        }

      }
      if (imageData) {
        return true
      }
    }
    return false
  }
  getImage(checkTextFirst = true){//第一个图片
    let imageData = MNNote.getImageFromNote(this,checkTextFirst)
    let image = imageData?UIImage.imageWithData(imageData):undefined
    return image
  }
  getImageData(checkTextFirst = true){
    return MNNote.getImageFromNote(this,checkTextFirst)
  }
  getImages(checkTextFirst = true){//所有图片
    let imageDatas = MNNote.getImagesFromNote(this,checkTextFirst)
    let images = imageDatas?imageDatas.map(imageData=>UIImage.imageWithData(imageData)):undefined
    return images
  }
  getImageDatas(checkTextFirst = true){//所有图片
    return MNNote.getImagesFromNote(this,checkTextFirst)
  }
  /**
   * Append text comments as much as you want.
   * @param {string[]} comments
   * @example
   * @returns {MNNote}
   * node.appendTextComments("a", "b", "c")
   */
  appendTextComments(...comments) {
    comments = MNUtil.unique(comments, true)
    const existComments = this.note.comments.filter(k => k.type === "TextNote")
    comments.forEach(comment => {
      if (
        comment &&
        existComments.every(k => k.type === "TextNote" && k.text !== comment)
      ) {
        this.note.appendTextComment(comment)
      }
    })
    return this
  }
  /**
   *
   * @param  {string} comment
   * @param  {number} index
   * @returns {MNNote}
   */
  appendMarkdownComment(comment,index=undefined){
    let validComment = comment && comment.trim()
    if (!validComment) {
      return this
    }
    try {
      this.note.appendMarkdownComment(comment)
    } catch (error) {
      this.note.appendTextComment(comment)
    }
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index,false)
    }
    return this
  }
  prependMarkdownComment(comment){
    this.appendMarkdownComment(comment,0)
  }
  /**
   *
   * @param  {string} comment
   * @param  {number} index
   * @returns {MNNote}
   */
  replaceWithMarkdownComment(comment,index=undefined){
    if (index !== undefined) {
      this.removeCommentByIndex(index)
    }
    let validComment = comment && comment.trim()
    if (!validComment) {
      return this
    }
    try {
      this.note.appendMarkdownComment(comment)
    } catch (error) {
      this.note.appendTextComment(comment)
    }
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index,false)
    }
    return this
  }
  /**
   *
   * @param  {string} comment
   * @param  {number} index
   * @returns {MNNote}
   */
  appendTextComment(comment,index=undefined){
    let validComment = comment && comment.trim()
    if (!validComment) {
      return this
    }
    this.note.appendTextComment(comment)
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index,false)
    }
    return this
  }

  prependTextComment(comment){
    this.appendTextComment(comment,0)
  }
  /**
   * 添加评论，可以通过option参数设置是否为markdown评论，以及评论的索引
   * @param  {string} comment
   * @param  {{index:number,markdown:boolean}} option
   * @returns {MNNote}
   */
  appendComment(comment,option={}){
    let validComment = comment && comment.trim()
    if (!validComment) {
      return this
    }
    let index = option.index
    if (option.markdown) {
      this.note.appendMarkdownComment(comment)
    }else{
      this.note.appendTextComment(comment)
    }
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index,false)
    }
    return this
  }
  /**
   * 添加评论，可以通过option参数设置是否为markdown评论
   * @param  {string} comment
   * @param  {{index:number,markdown:boolean}} option
   * @returns {MNNote}
   */
  prependComment(comment,option={}){
    option.index = 0
    this.appendComment(comment,option)
    return this
  }
  /**
   *
   * @param  {string} comment
   * @param  {number} index
   * @returns {MNNote}
   */
  replaceWithTextComment(comment,index=undefined){
    if (index !== undefined) {
      this.removeCommentByIndex(index)
    }
    let validComment = comment && comment.trim()
    if (!validComment) {
      return this
    }
    this.note.appendTextComment(comment)
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index,false)
    }
    return this
  }
  /**
   *
   * @param {string} html
   * @param {string} text
   * @param {CGSize} size
   * @param {string} tag
   * @param  {number} index
   * @returns {MNNote}
   */
  appendHtmlComment(html, text, size, tag, index = undefined){
    this.note.appendHtmlComment(html, text, size, tag)
    if (index !== undefined) {
      this.moveComment(this.note.comments.length-1, index)
    }
    return this
  }
  prependHtmlComment(html, text, size, tag){
    this.appendHtmlComment(html, text, size, tag, 0)
  }
  /**
   *
   * @param  {string[]} comments
   * @returns {MNNote}
   */
  appendMarkdownComments(...comments) {
    comments = unique(comments, true)
    const existComments = this.note.comments.filter(k => k.type === "TextNote")
    comments.forEach(comment => {
      if (
        comment &&
        existComments.every(k => k.type === "TextNote" && k.text !== comment)
      ) {
        if (this.note.appendMarkdownComment)
          this.note.appendMarkdownComment(comment)
        else this.note.appendTextComment(comment)
      }
    })
    return this
  }
  /**
   * 
   * @param {number[]} arr 
   * @returns {MNNote}
   */
  sortCommentsByNewIndices(arr){
    this.note.sortCommentsByNewIndices(arr)
    return this
  }
  /**
   * Moves a comment from one index to another within the note's comments array.
   * 
   * This method reorders the comments array by moving a comment from the specified `fromIndex` to the `toIndex`.
   * If the `fromIndex` or `toIndex` is out of bounds, it adjusts them to the nearest valid index.
   * If the `fromIndex` is the same as the `toIndex`, it does nothing and displays a message indicating no change.
   * 
   * @param {number} fromIndex - The current index of the comment to be moved.
   * @param {number} toIndex - The target index where the comment should be moved.
   * @returns {MNNote}
   */
  moveComment(fromIndex, toIndex,msg = true) {
  try {

    let length = this.comments.length;
    let arr = Array.from({ length: length }, (_, i) => i);
    let from = fromIndex
    let to = toIndex
    if (fromIndex < 0) {
      from = 0
    }
    if (fromIndex > (arr.length-1)) {
      from = arr.length-1
    }
    if (toIndex < 0) {
      to = 0
    }
    if (toIndex > (arr.length-1)) {
      to = arr.length-1
    }
    if (from == to) {
      if (msg) {
        MNUtil.showHUD("No change")
      }
      return
    }
    // 取出要移动的元素
    const element = arr.splice(to, 1)[0];
    // 将元素插入到目标位置
    arr.splice(from, 0, element);
    let targetArr = arr
    this.sortCommentsByNewIndices(targetArr)
    return this
    } catch (error) {
      MNNote.addErrorLog(error, "moveComment")
      return this
  }
  }
  /**
   * Moves a comment to a new position based on the specified action.
   * 
   * This method moves a comment from its current position to a new position based on the specified action.
   * The available actions are:
   * - "top": Moves the comment to the top of the list.
   * - "bottom": Moves the comment to the bottom of the list.
   * - "up": Moves the comment one position up in the list.
   * - "down": Moves the comment one position down in the list.
   * 
   * @param {number} fromIndex - The current index of the comment to be moved.
   * @param {string} action - The action to perform (top, bottom, up, down).
   * @returns {MNNote}
   */
  moveCommentByAction(fromIndex, action) {
    let targetIndex
    switch (action) {
      case "top":
        targetIndex = 0
        break;
      case "bottom":
        targetIndex = 100
        break;
      case "up":
        targetIndex = fromIndex-1
        break;
      case "down":
        targetIndex = fromIndex+1
        break;
      default:
        MNUtil.copy(action)
        MNUtil.showHUD("Invalid action!")
        return
    }
    this.moveComment(fromIndex, targetIndex)
    return this
  }
  /**
   * Retrieves the indices of comments that match the specified condition.
   * 
   * This method iterates through the comments of the current note and returns the indices of the comments that satisfy the given condition.
   * The condition can include filtering by comment type, inclusion or exclusion of specific text, or matching a regular expression.
   * 
   * @param {Object} condition - The condition to filter the comments.
   * @param {string[]} [condition.type] - The types of comments to include (e.g., "TextNote", "HtmlNote").
   * @param {string} [condition.include] - The text that must be included in the comment.
   * @param {string} [condition.exclude] - The text that must not be included in the comment.
   * @param {string} [condition.reg] - The regular expression that the comment must match.
   * @returns {number[]} An array of indices of the comments that match the condition.
   */
  getCommentIndicesByCondition(condition){
    let indices = []
    let types = []
    if ("type" in condition) {
      types = Array.isArray(condition.type) ? condition.type : [condition.type]
    }
    if ("types" in condition) {
      types = Array.isArray(condition.types) ? condition.types : [condition.types]
    }
    let excludeNoneTextComment = false
    if (condition.exclude || condition.include || condition.reg) {
      //提供特定参数时,不对非文字评论进行筛选
      excludeNoneTextComment = true
    }
    let noneTextCommentTypes = ["PaintNote","blankImageComment","mergedImageCommentWithDrawing","mergedImageComment"]
    this.note.comments.map((comment,commentIndex)=>{
      if (types.length && !MNComment.commentBelongsToType(comment, types)) {
        return
      }
      let newComment = MNComment.new(comment, commentIndex, this.note)
      if (excludeNoneTextComment && newComment.belongsToType(noneTextCommentTypes)) {
        //不对非文字评论进行筛选
        return
      }
      if (condition.include && !newComment.text.includes(condition.include)) {//指文字必须包含特定内容
        return
      }
      if (condition.exclude &&newComment.text.includes(condition.include)) {
        return
      }
      if (condition.reg) {
        let ptt = new RegExp(condition.reg,"g")
        if (!(ptt.test(comment.text))) {
          return
        }
      }
      indices.push(commentIndex)
    })
    return indices
  }
  /**
   *
   * @param {number} index
   * @returns {MNNote}
   */
  removeCommentByIndex(index){
    let length = this.note.comments.length
    if(index >= length){
      index = length-1
    }
    this.note.removeCommentByIndex(index)
    return this
  }
  /**
   *
   * @returns {MNNote}
   */
  removeAllComments(){
    let commentLength = this.comments.length
    for (let i = commentLength-1; i >= 0; i--) {
        this.removeCommentByIndex(i)
    }
    return this
  }
  /**
   *
   * @param {number[]} indices
   * @returns {MNNote}
   */
  removeCommentsByIndices(indices){
    let commentsLength = this.note.comments.length
    let newIndices = indices.map(index=>{
      if (index > commentsLength-1) {
        return commentsLength-1
      }
      if (index < 0) {
        return 0
      }
      return index
    })
    let sortedIndices = MNUtil.sort(newIndices,"decrement")
    sortedIndices.map(index=>{
      this.note.removeCommentByIndex(index)
    })
    return this
  }
  /**
   *
   * @param {{type:string,include:string,exclude:string,reg:string}} condition
   * @returns {MNNote}
   */
  removeCommentByCondition(condition){
    let indices = this.getCommentIndicesByCondition(condition)
    this.removeCommentsByIndices(indices)
    return this
  }
  /**
   * Remove all comment but tag, link and also the filterd. And tags and links will be sat at the end。
   * @param filter not deleted
   * @param f call a function after deleted, before set tag and link
   */
  async removeCommentButLinkTag(
    // 不删除
    filter,
    f
  ) {
    const { removedIndex, linkTags } = this.note.comments.reduce(
      (acc, comment, i) => {
        if (
          comment.type == "TextNote" &&
          (comment.text.includes("marginnote3app://note/") || comment.text.includes("marginnote4app://note/")||
            comment.text.startsWith("#"))
        ) {
          acc.linkTags.push(comment.text)
          acc.removedIndex.unshift(i)
        } else if (!filter(comment)) acc.removedIndex.unshift(i)
        return acc
      },
      {
        removedIndex: [],
        linkTags: []
      }
    )
    removedIndex.forEach(k => {
      this.note.removeCommentByIndex(k)
    })
    f && (await f(this))
    this.appendTextComments(...linkTags)
    return this
  }


  /**
   * @param {string[]} titles
   * append titles as much as you want
   */
  appendTitles(...titles) {
    const newTitle = MNUtil.unique([...this.titles, ...titles], true).join("; ")
    if (this.note.excerptText === this.note.noteTitle) {
      this.note.noteTitle = newTitle
      this.note.excerptText = newTitle
    } else {
      this.note.noteTitle = newTitle
    }
    return this
  }
  appendTitle(title){
    this.appendTitles([title])
    return this
  }
  prependTitle(title){
    this.titles.unshift(title)
    this.note.noteTitle = this.titles.join("; ")
    return this
  }
  /**
   * @param {string[]} tags
   * @returns {MNNote}
   * append tags as much as you want
   */
  appendTags(tags) {
  try {
    this.tidyupTags()
    // tags = this.tags.concat(tags)//MNUtil.unique(this.tags.concat(tags), true)
    tags = MNUtil.unique(this.tags.concat(tags), true)
    const lastComment = this.note.comments[this.note.comments.length - 1]
    if (lastComment?.type == "TextNote" && lastComment.text.startsWith("#")) {
      if (lastComment.text === tags.map(k => '#'+k).join(" ")) {
        return this
      }
      this.note.removeCommentByIndex(this.note.comments.length - 1)
    }
    this.appendTextComments(tags.map(k => {
      if (k.startsWith("#")) {
        return k
      }else{
        return '#'+k
      }
    }).join(" "))
    return this
  } catch (error) {
    MNNote.addErrorLog(error, "appendTags")
    return this
  }
  }
  /**
   * @param {string[]} tags
   * @returns {MNNote}
   * append tags as much as you want
   */
  removeTags(tagsToRemove) {
  try {
    this.tidyupTags()
    // tags = this.tags.concat(tags)//MNUtil.unique(this.tags.concat(tags), true)
    let tags = this.tags.filter(tag=>!tagsToRemove.includes(tag))
    // MNUtil.showHUD(tags)
    const lastComment = this.note.comments[this.note.comments.length - 1]
    if (lastComment?.type == "TextNote" && lastComment.text.startsWith("#")) {
      if (lastComment.text === tags.map(k => '#'+k).join(" ")) {
        return this
      }
      this.note.removeCommentByIndex(this.note.comments.length - 1)
    }
    this.appendTextComments(tags.map(k => '#'+k).join(" "))
    return this
  } catch (error) {
    MNNote.addErrorLog(error, "removeTags")
    return this
  }
  }
  /**
   * make sure tags are in the last comment
   */
  tidyupTags() {
    const existingTags= []
    const tagCommentIndex = []
    this.note.comments.forEach((comment, index) => {
      if (comment.type == "TextNote" && MNUtil._isTagComment_(comment)) {
        const tags = comment.text.split(" ").filter(k => k.startsWith("#"))
        existingTags.push(...tags.map(tag => tag.slice(1)))
        tagCommentIndex.unshift(index)
      }
    })

    tagCommentIndex.forEach(index => {
      this.note.removeCommentByIndex(index)
    })

    this.appendTextComments(
      MNUtil.unique(existingTags)
        .map(k => '#'+k)
        .join(" ")
    )
    return this
  }
  /**
   * @param {MbBookNote | string} comment
   * get comment index by comment
   */
  getCommentIndex(comment,includeHtmlComment = false) {
    const comments = this.note.comments
    for (let i = 0; i < comments.length; i++) {
      const _comment = comments[i]
      if (typeof comment == "string") {
        if (includeHtmlComment) {
          if ((_comment.type == "TextNote" || _comment.type == "HtmlNote" )&& _comment.text == comment) return i
        }else{
          if (_comment.type == "TextNote" && _comment.text == comment) return i
        }
      } else if (
        _comment.type == "LinkNote" &&
        _comment.noteid == comment.noteId
      )
        return i
    }
    return -1
  }
  /**
   * Clear the format of the current note.
   * @returns {MNNote}
   */
  clearFormat(){
    this.note.clearFormat()
    return this
  }
  /**
   * Appends a note link to the current note.
   * 
   * This method appends a note link to the current note based on the specified type. The type can be "Both", "To", or "From".
   * If the type is "Both", the note link is added to both the current note and the target note.
   * If the type is "To", the note link is added only to the current note.
   * If the type is "From", the note link is added only to the target note.
   * 
   * @param {MNNote|MbBookNote} note - The note to which the link should be added.
   * @param {string} type - The type of link to add ("Both", "To", or "From").
   * @returns {MNNote}
   */
  appendNoteLink(note,type="To"){
  try {
    switch (MNUtil.typeOf(note)) {
      case "MNNote":
        switch (type) {
          case "Both":
            this.note.appendNoteLink(note.note)
            note.note.appendNoteLink(this.note)
            break;
          case "To":
            this.note.appendNoteLink(note.note)
            break;
          case "From":
            note.note.appendNoteLink(this.note)
          default:
            break;
        }
        break;
      case "NoteURL":
      case "NoteId":
        let targetNote = MNNote.new(note)
        switch (type) {
          case "Both":
            this.note.appendNoteLink(targetNote.note)
            targetNote.note.appendNoteLink(this.note)
            break;
          case "To":
            this.note.appendNoteLink(targetNote.note)
            break;
          case "From":
            targetNote.note.appendNoteLink(this.note)
            break;
          default:
            break;
        }
        break;
      case "MbBookNote":
        switch (type) {
          case "Both":
            this.note.appendNoteLink(note)
            note.appendNoteLink(this.note)
            break;
          case "To":
            this.note.appendNoteLink(note)
            break;
          case "From":
            note.appendNoteLink(this.note)
          default:
            break;
        }
        break;
      default:
        break;
    }
    return this
  } catch (error) {
    MNNote.addErrorLog(error, "appendNoteLink")
    return this
  }
  }
  /**
   * 
   * @param {Object} editConfig
   * @param {boolean} refresh 
   */
  editFunc(editConfig){
    if ("deleteNote" in editConfig && editConfig.deleteNote) {
      this.delete()
      //没有必要做其他编辑
      return true
    }
    if ("color" in editConfig) {
      this.color = editConfig.color
    }
    if ("excerptText" in editConfig) {
      this.excerptText = editConfig.excerptText
    }
    if ("excerptTextMarkdown" in editConfig) {
      this.excerptTextMarkdown = editConfig.excerptTextMarkdown
    }
    if ("title" in editConfig) {
      this.title = editConfig.title
    }
    if ("tags" in editConfig) {
      this.appendTags(editConfig.tags)
    }
    if ("markdownComment" in editConfig) {
      if ("markdownCommentIndex" in editConfig) {
        this.appendMarkdownComment(editConfig.markdownComment, editConfig.markdownCommentIndex)
      }else{
        this.appendMarkdownComment(editConfig.markdownComment)
      }
    }
    if ("textComment" in editConfig) {
      if ("textCommentIndex" in editConfig) {
        this.appendTextComment(editConfig.textComment, editConfig.textCommentIndex)
      }else{
        this.appendTextComment(editConfig.textComment)
      }
    }
    if ("tagsToRemove" in editConfig) {
      this.removeTags(editConfig.tagsToRemove)
    }
  }
  /**
   * 通过一个json配置来应用更改
   * @param {Object} editConfig
   * @param {boolean} undoGrouping
   * @param {boolean} refresh 
   * @returns {MNNote}
   */
  applyEdit(editConfig,undoGrouping = true,refresh = true){
    if (undoGrouping) {
      if (refresh) {
        MNUtil.undoGrouping(()=>{
          this.editFunc(editConfig)
        })
      }else{
        MNUtil.undoGroupingNotRefresh(()=>{
          this.editFunc(editConfig)
        })
      }
    }else{
      this.editFunc(editConfig)
    }
    return this
  }
  /**
   *
   * @returns {MNNote}
   */
  clone() {
    let notebookId = MNUtil.currentNotebookId
    let noteIds = MNUtil.db.cloneNotesToTopic([this.note], notebookId)
    return MNNote.new(noteIds[0])
  }
  /**
   *
   * @param {number} [delay=0]
   * @returns {Promise<MNNote>}
   */
  async focusInMindMap(delay = 0){
    if (this.notebookId && this.notebookId !== MNUtil.currentNotebookId) {
      MNUtil.showHUD("Note not in current notebook")
      return this
    }
    if (delay) {
      await MNUtil.delay(delay)
    }
    MNUtil.studyController.focusNoteInMindMapById(this.noteId)
    return this
  }
  /**
   *
   * @param {number} [delay=0]
   * @returns {Promise<MNNote>}
   */
  async focusInDocument(delay = 0){
    if (delay) {
      await MNUtil.delay(delay)
    }
    MNUtil.studyController.focusNoteInDocumentById(this.noteId)
    return this
  }
  /**
   *
   * @param {number} [delay=0]
   * @returns {Promise<MNNote>}
   */
  async focusInFloatMindMap(delay = 0){
    if (delay) {
      await MNUtil.delay(delay)
    }
    MNUtil.studyController.focusNoteInFloatMindMapById(this.noteId)
    return this
  }
  copyURL(){
    MNUtil.copy(this.noteURL)
  }
  /**
   * 
   */
  getNoteObject(opt={first:true}) {
    let note = this
    try {
    if (!note) {
      return undefined
    }
    let noteConfig = config
    noteConfig.id = note.noteId
    if (opt.first) {
      noteConfig.notebook = {
        id:note.notebookId,
        name:MNUtil.getNoteBookById(note.notebookId).title,
      }
    }
    noteConfig.title = note.noteTitle
    noteConfig.url = note.noteURL
    noteConfig.excerptText = note.excerptText
    noteConfig.isMarkdownExcerpt = note.excerptTextMarkdown
    if (this.isBlankNote(note)) {
      noteConfig.isImageExcerpt = false
    }else{
      noteConfig.isImageExcerpt = !!note.excerptPic
    }
    if (note.textFirst !== undefined) {
      noteConfig.textFirst = note.textFirst
    }else{
      noteConfig.textFirst = false
    }
    noteConfig.date = {
      create:note.createDate.toLocaleString(),
      modify:note.modifiedDate.toLocaleString(),
    }
    noteConfig.allText = note.allNoteText()
    noteConfig.tags = note.tags
    noteConfig.hashTags = note.tags.map(tag=> ("#"+tag)).join(" ")
    noteConfig.hasTag = note.tags.length > 0
    noteConfig.hasComment = note.comments.length > 0
    noteConfig.hasChild = note.childNotes.length > 0
    if (note.colorIndex !== undefined) {
      noteConfig.colorHex = this.getNoteColorHex
      noteConfig.color = {}
      noteConfig.color.lightYellow = note.colorIndex === 0
      noteConfig.color.lightGreen = note.colorIndex === 1
      noteConfig.color.lightBlue = note.colorIndex === 2
      noteConfig.color.lightRed = note.colorIndex === 3
      noteConfig.color.yellow = note.colorIndex === 4
      noteConfig.color.green = note.colorIndex === 5
      noteConfig.color.blue = note.colorIndex === 6
      noteConfig.color.red = note.colorIndex === 7
      noteConfig.color.orange = note.colorIndex === 8
      noteConfig.color.darkGreen = note.colorIndex === 9
      noteConfig.color.darkBlue = note.colorIndex === 10
      noteConfig.color.deepRed = note.colorIndex === 11
      noteConfig.color.white = note.colorIndex === 12
      noteConfig.color.lightGray = note.colorIndex === 13
      noteConfig.color.darkGray = note.colorIndex === 14
      noteConfig.color.purple = note.colorIndex === 15
    }
    if (note.docMd5 && MNUtil.getDocById(note.docMd5)) {
      noteConfig.docName = MNUtil.getDocById(note.docMd5).docTitle
    }
    noteConfig.hasDoc = !!noteConfig.docName
    if (note.childMindMap) {
      noteConfig.childMindMap = this.getNoteObject(note.childMindMap,{first:false})
    }
    noteConfig.inMainMindMap = !noteConfig.childMindMap
    noteConfig.inChildMindMap = !!noteConfig.childMindMap
    if ("parent" in opt && opt.parent && note.parentNote) {
      if (opt.parentLevel && opt.parentLevel > 0) {
        noteConfig.parent = this.getNoteObject(note.parentNote,{parentLevel:opt.parentLevel-1,parent:true,first:false})
      }else{
        noteConfig.parent = this.getNoteObject(note.parentNote,{first:false})
      }
    }
    noteConfig.hasParent = "parent" in noteConfig
    if ("child" in opt && opt.child && note.childNotes) {
      noteConfig.child = note.childNotes.map(note=>this.getNoteObject(note,{first:false}))
    }
    return noteConfig
    } catch (error) {
      MNNote.addErrorLog(error, "MNNote.getNoteObject")
      return {}
    }
  }
  static addErrorLog(error,source,info,showHUD = true){
    if (showHUD) {
      MNUtil.showHUD("MNNote Error ("+source+"): "+error)
    }
    let tem = {source:source,time:(new Date(Date.now())).toString()}
    if (error.detail) {
      tem.error = {message:error.message,detail:error.detail}
    }else{
      tem.error = error.message
    }
    if (info) {
      tem.info = info
    }
    MNUtil.errorLog.push(tem)
    MNUtil.copy(MNUtil.errorLog)
    if (typeof MNUtil.log !== 'undefined') {
      this.log({
        level:"error",
        message:source,
        detail:tem,
      })
    }
  }
  /**
   *
   * 
   * This method checks if the note has an excerpt picture. If it does, it retrieves the image data and the excerpt text.
   * If the note does not have an excerpt picture, it only retrieves the excerpt text. The method returns an object containing
   * arrays of OCR text, HTML text, and Markdown text.
   * 
   * @param {MbBookNote} note - The note from which to retrieve the excerpt text and image data.
   * @returns {{ocr: string[], html: string[], md: string[]}} An object containing arrays of OCR text, HTML text, and Markdown text.
   */
  static getNoteExcerptTextPic(note) {
    const acc = {
      ocr: [],
      html: [],
      md: []
    }
    const text = note.excerptText?.trim()
    if (note.excerptPic) {
      const imgs = MNNote.exportPic(note.excerptPic)
      if (imgs)
        Object.entries(imgs).forEach(([k, v]) => {
          if (k in acc) acc[k].push(v)
        })
      if (text) {
        acc.ocr.push(text)
      }
    } else {
      if (text) {
        Object.values(acc).forEach(k => k.push(text))
      }
    }
    return acc
  }
  /**
   * Get picture base64 code wrapped in html and markdown
   * @param {MNPic} pic
   * @returns
   * - html: '<img class="MNPic" src="data:image/jpeg;base64,${base64}"/>'
   * - md: '![MNPic](data:image/jpeg;base64,${base64})'
   */
  static exportPic(pic) {
    const base64 = MNUtil.db.getMediaByHash(pic.paint)?.base64Encoding()
    if (base64)
      return {
        html: `<img class="MNPic" src="data:image/jpeg;base64,${base64}"/>`,
        md: `![MNPic](data:image/jpeg;base64,${base64})`
      }
  }
  static focusInMindMapById(noteId,delay = 0){
    MNUtil.focusNoteInMindMapById(noteId,delay)
  }
  static focusInDocumentById(noteId,delay = 0){
    MNUtil.focusNoteInDocumentById(noteId,delay = 0)
  }
  static focusInFloatMindMapById(noteId,delay = 0){
    MNUtil.focusNoteInFloatMindMapById(noteId,delay = 0)
  }
  /**
   *
   * @param {MbBookNote|string} note
   */
  static focusInMindMap(note,delay=0){
    let noteId = MNUtil.getNoteId(note);
    if (noteId) {
      MNUtil.focusNoteInMindMapById(noteId,delay)
    }
  }
  /**
   *
   * @param {MbBookNote|string} note
   */
  static focusInDocument(note,delay){
    let noteId = MNUtil.getNoteId(note);
    if (noteId) {
      MNUtil.focusNoteInDocumentById(noteId,delay)
    }
  }
  static focusInFloatMindMap(note,delay){
    let noteId = MNUtil.getNoteId(note);
    if (noteId) {
      MNUtil.focusNoteInFloatMindMapById(noteId,delay)
    }
  }
  static get currentChildMap(){
  try {
    let mindmapView = MNUtil.mindmapView
    if (!mindmapView || !mindmapView.mindmapNodes || mindmapView.mindmapNodes.length === 0) {
      return undefined
    }
    if (mindmapView.mindmapNodes[0].note?.childMindMap) {
      return this.new(mindmapView.mindmapNodes[0].note.childMindMap.noteId)
    }else{
      return undefined
    }
  } catch (error) {
    MNNote.addErrorLog(error, "MNNote.currentChildMap")
    return undefined
  }
  }
  /**
   * Retrieves the currently focused note in the mind map or document.
   * 
   * This method checks for the focused note in the following order:
   * 1. If the notebook controller is visible and has a focused note, it returns that note.
   * 2. If the document map split mode is enabled, it checks the current document controller and all document controllers for a focused note.
   * 3. If a pop-up note info is available, it returns the note from the pop-up note info.
   * 
   * @returns {MNNote|undefined} The currently focused note, or undefined if no note is focused.
   */
  static get focusNote(){
    return this.getFocusNote()
  }
  /**
   * Retrieves the currently focused note in the mind map or document.
   * 
   * This method checks for the focused note in the following order:
   * 1. If the notebook controller is visible and has a focused note, it returns that note.
   * 2. If the document map split mode is enabled, it checks the current document controller and all document controllers for a focused note.
   * 3. If a pop-up note info is available, it returns the note from the pop-up note info.
   * 
   * @returns {MNNote|undefined} The currently focused note, or undefined if no note is focused.
   */
  static getFocusNote() {
    let notebookController = MNUtil.notebookController
    if (!notebookController.view.hidden && notebookController.mindmapView && notebookController.focusNote) {
      return MNNote.new(notebookController.focusNote)
    }
    let notebookType = MNUtil.currentNotebook.flags
    if (notebookType === 1) {//文档模式下，直接返回当前文档控制器的焦点笔记
      let note = MNUtil.currentDocController.focusNote
      if (note) {
        return MNNote.new(note)
      }
    }
    if (MNUtil.docMapSplitMode) {//不为0则表示documentControllers存在
      let note = MNUtil.currentDocController.focusNote
      if (note) {
        return MNNote.new(note)
      }
      let focusNote
      let docNumber = MNUtil.docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = MNUtil.docControllers[i];
        focusNote = docController.focusNote
        if (focusNote) {
          return MNNote.new(focusNote)
        }
      }
      if (MNUtil.popUpNoteInfo) {
        return MNNote.new(MNUtil.popUpNoteInfo.noteId)
      }
    }
    return undefined
  }

    /**
   * 
   * @param {MbBookNote|MNNote} note 
   * @param {boolean} checkTextFirst 
   * @returns {boolean}
   */
  static hasImageInNote(note,checkTextFirst = true){
    let type = MNUtil.typeOf(note)
    if (type === "MNNote") {
      return note.hasImage(checkTextFirst)
    }else if (type === "MbBookNote") {
      note = MNNote.new(note.noteId)
      return note.hasImage(checkTextFirst)
    }

    if (note.excerptPic && !note.textFirst) {
      return true
    }
    if (note.comments && note.comments.length) {
      let comment = note.comments.find(c=>c.type==="PaintNote")
      if (comment) {
        return true
      }
    }
    return false
  }
  static fromSelection(docController = MNUtil.currentDocController){
    let selection = MNUtil.currentSelection
    if (!selection.onSelection) {
      return undefined
    }
    return MNNote.new(docController.highlightFromSelection())
  }
  /**
   * Retrieves the focus notes in the current context.
   * 
   * This method checks for focus notes in various contexts such as the mind map, document controllers, and pop-up note info.
   * It returns an array of MNNote instances representing the focus notes. If no focus notes are found, it returns an empty array.
   * 
   * @returns {MNNote[]} An array of MNNote instances representing the focus notes.
   */
  static get focusNotes(){
    return this.getFocusNotes()
  }
  /**
   * Retrieves the focus notes in the current context.
   * 
   * This method checks for focus notes in various contexts such as the mind map, document controllers, and pop-up note info.
   * It returns an array of MNNote instances representing the focus notes. If no focus notes are found, it returns an empty array.
   * 
   * @returns {MNNote[]} An array of MNNote instances representing the focus notes.
   */
  static getFocusNotes() {
    let notebookController = MNUtil.notebookController
    if (!notebookController.view.hidden && notebookController.mindmapView && notebookController.mindmapView.selViewLst && notebookController.mindmapView.selViewLst.length) {
      let selViewLst = notebookController.mindmapView.selViewLst
      return selViewLst.map(tem=>{
        return this.new(tem.note.note)
      })
    }
    let notebookType = MNUtil.currentNotebook.flags
    if (notebookType === 1) {//文档模式下，直接返回当前文档控制器的焦点笔记
      let note = MNUtil.currentDocController.focusNote
      if (note) {
        return [MNNote.new(note)]
      }
    }
    if (MNUtil.docMapSplitMode) {//不为0则表示documentControllers存在
      let note = MNUtil.currentDocController.focusNote
      if (note) {
        return [this.new(note)]
      }
      let focusNote
      let docNumber = MNUtil.docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = MNUtil.docControllers[i];
        focusNote = docController.focusNote
        if (focusNote) {
          return [this.new(focusNote)]
        }
      }
    }
    if (MNUtil.popUpNoteInfo) {
        return [this.new(MNUtil.popUpNoteInfo.noteId)]
    }
    //如果两个上面两个都没有，那就可能是小窗里打开的
    if (notebookController.focusNote) {
      return [this.new(notebookController.focusNote)]
    }
    return []
  }
  static getSelectedNotes(){
    return this.getFocusNotes()
  }
  /**
   * 
   * @param {MNNote} note 
   * @returns {number[]}
   */
  static getNoteRelatedPageNos(note){
  try {
    if (!note) {
      return []
    }
    let notes = note.notes
    let pageNos = []
    for (let i = 0; i < notes.length; i++) {
      const note = notes[i];
      let startPage = note.note.startPage
      let endPage = note.note.endPage
      if (startPage !== undefined) {
        pageNos.push(startPage)
      }
      if (endPage !== undefined && endPage > startPage) {
        for (let j = startPage + 1; j < endPage; j++) {
          pageNos.push(j)
        }
      }
    }
    let uniquePageNos = Array.from(new Set(pageNos))
    return uniquePageNos
    
  } catch (error) {
    this.addErrorLog(error, "getNoteRelatedPageNos")
    return []
  }
  }
/**
 * 
 * @param {MNNote[]} notes 
 * @returns 
 */
static buildHierarchy(notes) {
try {

  const tree = [];
  const map = {}; // Helper to quickly find notes by their ID

  // First pass: Create a map of notes and initialize a 'children' array for each.
  notes.forEach(note => {
    map[note.id] = { id:note.id, children: [] }; // Store a copy and add children array
  });
  // Second pass: Populate the 'children' arrays and identify root nodes.
  notes.forEach(note => {
    let parentId = note.parentNoteId
    if (parentId && map[parentId]) {
      // If it has a parent and the parent exists in our map, add it to parent's children
      map[parentId].children.push(map[note.id]);
    } else {
      // Otherwise, it's a root node (or an orphan if parentId is invalid but present)
      tree.push(map[note.id]);
    }
  });

  return tree;
  
} catch (error) {
  return []
}
}
  /**
   * 
   * @param {*} range 
   * @returns {MNNote[]}
   */
  static getNotesByRange(range){
  try {

    if (range === undefined) {
      return [MNNote.getFocusNote()]
    }
    switch (range) {
      case "currentNotes":
        return MNNote.getFocusNotes()
      case "childNotes":
        let childNotes = []
        MNNote.getFocusNotes().map(note=>{
          childNotes = childNotes.concat(note.childNotes)
        })
        return childNotes
      case "descendants":
      case "descendantNotes"://所有后代节点
        let descendantNotes = []
        // let descendantNotes = []
        let focusNotes = MNNote.getFocusNotes()
        if (focusNotes.length === 0) {
          MNUtil.showHUD("No notes found")
          return []
        }
        let topLevelNotes = this.buildHierarchy(focusNotes).map(o=>MNNote.new(o.id))
        // let notesWithoutDescendants = focusNotes.filter(note=>!note.hasDescendantNodes)
        topLevelNotes.map(note=>{
          descendantNotes = descendantNotes.concat(note.descendantNodes.descendant)
        })
        return descendantNotes
      default:
        return [MNNote.getFocusNote()]
    }
    
  } catch (error) {
    MNNote.addErrorLog(error, "MNNote.getNotesByRange")
    return []
  }
  }
  /**
   * Clones a note to the specified notebook.
   * 
   * This method clones the provided note to the specified notebook. The note object can be of various types:
   * - An MbBookNote instance.
   * - A string representing a note URL.
   * - A string representing a note ID.
   * - A configuration object for creating a new note.
   * 
   * If the note object is a string representing a note URL, the method will attempt to retrieve the corresponding note from the URL.
   * If the note object is a string representing a note ID, the method will attempt to retrieve the corresponding note from the database.
   * If the note object is a configuration object, the method will create a new note with the specified properties.
   * 
   * @param {MbBookNote|string|MNNote} note - The note object to clone.
   * @param {string} [notebookId=MNUtil.currentNotebookId] - The ID of the notebook to clone the note to.
   * @returns {MNNote|undefined} The cloned MNNote instance or undefined if the note object is invalid.
   */
  static clone(note, notebookId = MNUtil.currentNotebookId) {
    let noteIds = []
    // let notebookId = MNUtil.currentNotebookId
    switch (MNUtil.typeOf(note)) {
      case "NoteURL":
        let noteFromURL = MNUtil.getNoteById(MNUtil.getNoteIdByURL(note))
        if (!noteFromURL) {
          MNNote.addErrorLog("Note not exist!", "clone", note)
          return undefined
        }
        noteIds = MNUtil.db.cloneNotesToTopic([noteFromURL], notebookId)
        return MNNote.new(noteIds[0])
      case "NoteId":
      case "string":
        let targetNote = MNUtil.getNoteById(note)
        if (!targetNote) {
          MNNote.addErrorLog("Note not exist!", "clone", note)
          return undefined
        }
        noteIds = MNUtil.db.cloneNotesToTopic([targetNote], notebookId)
        return MNNote.new(noteIds[0])
      case "MbBookNote":
        noteIds = MNUtil.db.cloneNotesToTopic([note], notebookId)
        return MNNote.new(noteIds[0])
      case "MNNote":
        noteIds = MNUtil.db.cloneNotesToTopic([note.note], notebookId)
        return MNNote.new(noteIds[0])
      default:
        break;
    }
  }
/**
   * Retrieves the image data from the current document controller or other document controllers if the document map split mode is enabled.
   * 
   * This method checks for image data in the current document controller's selection. If no image is found, it checks the focused note within the current document controller.
   * If the document map split mode is enabled, it iterates through all document controllers to find the image data. If a pop-up selection info is available, it also checks the associated document controller.
   * 
   * @param {boolean} [checkImageFromNote=true] - Whether to check the focused note for image data.
   * @param {boolean} [checkDocMapSplitMode=false] - Whether to check other document controllers if the document map split mode is enabled.
   * @returns {string|undefined} The image data if found, otherwise undefined.
   */
  static getImageIdFromNote(note,checkTextFirst = true) {
    if (note.excerptPic) {
      let isBlankNote = MNUtil.isBlankNote(note)
      if (isBlankNote) {//实际为文字留白
        let text = note.excerptText
        if (note.excerptTextMarkdown) {
          if (MNUtil.hasMNImages(text.trim())) {
            return MNUtil.getMNImageIdFromMarkdown(text)
          }
        }
      }else{
        if (checkTextFirst && note.textFirst) {
          //检查发现图片已经转为文本，因此略过
        }else{
          return note.excerptPic.paint
        }
      }
    }else{
      let text = note.excerptText
      if (note.excerptTextMarkdown) {
        if (MNUtil.hasMNImages(text.trim())) {
          return MNUtil.getMNImageIdFromMarkdown(text)
        }
      }
    }
    if (note.comments.length) {
      let imageData = undefined
      for (let i = 0; i < note.comments.length; i++) {
        const comment = note.comments[i];
        if (comment.type === 'PaintNote' && comment.paint) {
          imageData = comment.paint
          break
        }
        if (comment.type === "LinkNote" && comment.q_hpic && comment.q_hpic.paint) {
          imageData = comment.q_hpic.paint
          break
        }

      }
      if (imageData) {
        return imageData
      }
    }
    return undefined
  }
  /**
   * Retrieves the image data from the current document controller or other document controllers if the document map split mode is enabled.
   * 
   * This method checks for image data in the current document controller's selection. If no image is found, it checks the focused note within the current document controller.
   * If the document map split mode is enabled, it iterates through all document controllers to find the image data. If a pop-up selection info is available, it also checks the associated document controller.
   * 
   * @param {boolean} [checkImageFromNote=true] - Whether to check the focused note for image data.
   * @param {boolean} [checkDocMapSplitMode=false] - Whether to check other document controllers if the document map split mode is enabled.
   * @returns {NSData|undefined} The image data if found, otherwise undefined.
   */
  static getImageFromNote(note,checkTextFirst = true) {
    if (note.excerptPic) {
      let isBlankNote = MNUtil.isBlankNote(note)
      if (isBlankNote) {//实际为文字留白
        let text = note.excerptText
        if (note.excerptTextMarkdown) {
          if (MNUtil.hasMNImages(text.trim())) {
            return MNUtil.getMNImageFromMarkdown(text)
          }
        }
      }else{
        if (checkTextFirst && note.textFirst) {
          //检查发现图片已经转为文本，因此略过
        }else{
          return MNUtil.getMediaByHash(note.excerptPic.paint)
        }
      }
    }else{
      let text = note.excerptText
      if (note.excerptTextMarkdown) {
        if (MNUtil.hasMNImages(text.trim())) {
          return MNUtil.getMNImageFromMarkdown(text)
        }
      }
    }
    if (note.comments.length) {
      let imageData = undefined
      for (let i = 0; i < note.comments.length; i++) {
        const comment = note.comments[i];
        if (comment.type === 'PaintNote' && comment.paint) {
          imageData = MNUtil.getMediaByHash(comment.paint)
          break
        }
        if (comment.type === "LinkNote" && comment.q_hpic && comment.q_hpic.paint) {
          imageData = MNUtil.getMediaByHash(comment.q_hpic.paint)
          break
        }

      }
      if (imageData) {
        return imageData
      }
    }
    return undefined
  }
  /**
   * Retrieves the image data from the current document controller or other document controllers if the document map split mode is enabled.
   * 
   * This method checks for image data in the current document controller's selection. If no image is found, it checks the focused note within the current document controller.
   * If the document map split mode is enabled, it iterates through all document controllers to find the image data. If a pop-up selection info is available, it also checks the associated document controller.
   * 
   * @param {boolean} [checkImageFromNote=false] - Whether to check the focused note for image data.
   * @param {boolean} [checkDocMapSplitMode=false] - Whether to check other document controllers if the document map split mode is enabled.
   * @returns {{data:NSData,source:string,index:number}} The image data if found, otherwise undefined.
   */
  static getImageInfoFromNote(note,checkTextFirst = false) {
    let imageInfo = {}
    if (note.excerptPic) {
      let isBlankNote = MNUtil.isBlankNote(note)
      if (isBlankNote) {//实际为文字留白
        let text = note.excerptText
        if (note.excerptTextMarkdown) {
          if (MNUtil.hasMNImages(text.trim())) {
            imageInfo.data = MNUtil.getMNImageFromMarkdown(text)
            imageInfo.source = "excerptTextMarkdown"
          }
        }
      }else{
        if (checkTextFirst && note.textFirst) {
          //检查发现图片已经转为文本，因此略过
        }else{
          imageInfo.data = MNUtil.getMediaByHash(note.excerptPic.paint)
          imageInfo.source = "excerptPic"
        }
      }
    }else{
      let text = note.excerptText
      if (note.excerptTextMarkdown) {
        if (MNUtil.hasMNImages(text.trim())) {
          imageInfo.data = MNUtil.getMNImageFromMarkdown(text)
          imageInfo.source = "excerptTextMarkdown"
        }
      }
    }
    if (note.comments.length) {
      for (let i = 0; i < note.comments.length; i++) {
        const comment = note.comments[i];
        if (comment.type === 'PaintNote' && comment.paint) {
          imageInfo.data = MNUtil.getMediaByHash(comment.paint)
          imageInfo.source = "PaintNote"
          imageInfo.index = i
          break
        }
        if (comment.type === "LinkNote" && comment.q_hpic && comment.q_hpic.paint) {
          imageInfo.data = MNUtil.getMediaByHash(comment.q_hpic.paint)
          imageInfo.source = "LinkNote"
          imageInfo.index = i
          break
        }
      }
    }
    return imageInfo
  }
  /**
   * Retrieves the image data from the current document controller or other document controllers if the document map split mode is enabled.
   * 
   * This method checks for image data in the current document controller's selection. If no image is found, it checks the focused note within the current document controller.
   * If the document map split mode is enabled, it iterates through all document controllers to find the image data. If a pop-up selection info is available, it also checks the associated document controller.
   * 
   * @param {boolean} [checkImageFromNote=false] - Whether to check the focused note for image data.
   * @param {boolean} [checkDocMapSplitMode=false] - Whether to check other document controllers if the document map split mode is enabled.
   * @returns {NSData[]|undefined} The image data if found, otherwise undefined.
   */
  static getImagesFromNote(note,checkTextFirst = false) {
    let imageDatas = []
    if (note.excerptPic) {
      let isBlankNote = MNUtil.isBlankNote(note)
      if (isBlankNote) {//实际为文字留白
        let text = note.excerptText
        if (note.excerptTextMarkdown) {
          if (MNUtil.hasMNImages(text.trim())) {
            imageDatas.push(MNUtil.getMNImageFromMarkdown(text))
          }
        }
      }else{
        if (checkTextFirst && note.textFirst) {
          //检查发现图片已经转为文本，因此略过
        }else{
          imageDatas.push(MNUtil.getMediaByHash(note.excerptPic.paint))
        }
      }
    }else{
      let text = note.excerptText
      if (note.excerptTextMarkdown) {
        if (MNUtil.hasMNImages(text.trim())) {
          imageDatas.push(MNUtil.getMNImageFromMarkdown(text))
        }else{
          this.log("No images found in excerptTextMarkdown")
        }
      }
    }
    if (note.comments.length) {
      for (let i = 0; i < note.comments.length; i++) {
        const comment = note.comments[i];
        if (comment.type === 'PaintNote' && comment.paint) {
          imageDatas.push(MNUtil.getMediaByHash(comment.paint))
        }else if (comment.type === "LinkNote" && comment.q_hpic && comment.q_hpic.paint) {
          imageDatas.push(MNUtil.getMediaByHash(comment.q_hpic.paint))
        }
      }
    }
    return imageDatas
  }
  /**
   * 笔记可能已经被删除
   * @param {string} noteId 
   * @returns {boolean}
   */
  static exist(noteId){
    if(!noteId || !noteId.trim()){
      return false
    }
    if (MNUtil.db.getNoteById(noteId)) {
      return true
    }
    return false
  }
}

class MNComment {
  /** @type {string} */
  type;
  /** @type {string|undefined} */
  originalNoteId;
  /** @type {number|undefined} */
  index;
  /**
   * 
   * @param {NoteComment} comment 
   */
  constructor(comment) {
    this.type = MNComment.getCommentType(comment)
    this.detail = comment
  }
  get imageId(){
    switch (this.type) {
      case "blankImageComment":
      case "mergedImageCommentWithDrawing":
      case "mergedImageComment":
        return this.detail.q_hpic.paint
      case "drawingComment":
      case "imageCommentWithDrawing":
      case "imageComment":
        return this.detail.paint
      default:
        MNUtil.showHUD("Invalid type: "+this.type)
        return undefined
    }
  }
  get imageData() {
    switch (this.type) {
      case "blankImageComment":
      case "mergedImageCommentWithDrawing":
      case "mergedImageComment":
        return MNUtil.getMediaByHash(this.detail.q_hpic.paint)
      case "drawingComment":
      case "imageCommentWithDrawing":
      case "imageComment":
        return MNUtil.getMediaByHash(this.detail.paint)
      default:
        MNUtil.showHUD("Invalid type: "+this.type)
        return undefined
    }
  }
  get videoId(){
    if (this.type === "audioComment") {
      return this.detail.audio
    }
    return undefined
  }
  get audioId(){
    if (this.type === "audioComment") {
      return this.detail.audio
    }
    return undefined
  }
  get audioData(){
    if (this.type === "audioComment") {
      return MNUtil.getMediaByHash(this.detail.audio)
    }
    return undefined
  }
  get videoData(){
    if (this.type === "audioComment") {
      return MNUtil.getMediaByHash(this.detail.audio)
    }
    return undefined
  }

  get text(){
    if (this.detail.text) {
      return this.detail.text
    }
    if (this.detail.q_htext) {
      return this.detail.q_htext
    }
    MNUtil.showHUD("No available text")
    return ""
  }
  get markdown(){
    return this.type === "markdownComment"
  }
  /**
   * 
   * @param {Boolean} markdown 
   */
  set markdown(markdown){
    switch (this.type) {
        case "blankTextComment":
        case "mergedImageComment":
        case "mergedTextComment":
        case "blankImageComment":
        case "mergedImageCommentWithDrawing":
        case "drawingComment":
        case "imageCommentWithDrawing":
        case "imageComment":
        case "markdownComment":
        return
      default:
        break;
    }
    if (markdown) {
      if (this.type === "markdownComment") {
        return
      }
      if (this.originalNoteId) {
        let note = MNNote.new(this.originalNoteId)
        note.replaceWithMarkdownComment(this.detail.text,this.index)
      }
    }else{
      if (this.type === "markdownComment" && this.originalNoteId) {
        let note = MNNote.new(this.originalNoteId)
        note.replaceWithTextComment(this.detail.text,this.index)
      }
    }
  }
  set text(text){
    if (this.originalNoteId) {
      let note = MNNote.new(this.originalNoteId)
      switch (this.type) {
        case "markdownComment":
          this.detail.text = text
          note.replaceWithMarkdownComment(text,this.index)
          // note.removeCommentByIndex(this.index)
          // note.appendMarkdownComment(text, this.index)
          break;
        case "textComment":
          this.detail.text = text
          note.replaceWithTextComment(text,this.index)
          // note.removeCommentByIndex(this.index)
          // note.appendTextComment(text, this.index)
          break;
        case "linkComment":
          let noteURLs = MNUtil.extractMarginNoteLinks(text)//提取markdown格式链接
          let targetNote = MNNote.new(noteURLs[0])
          this.replaceLink(targetNote)
          // if (noteURLs.length && MNNote.new(noteURLs[0])) {
          //   if (this.linkDirection === "both") {
          //     this.removeBackLink()//先去除原反链
          //     this.detail.text = noteURLs[0]
          //     note.replaceWithTextComment(noteURLs[0],this.index)
          //     this.addBackLink(true)
          //   }else{be
          //     this.detail.text = noteURLs[0]
          //     note.replaceWithTextComment(noteURLs[0],this.index)
          //   }
          // }
          // note.removeCommentByIndex(this.index)
          // note.appendTextComment(text, this.index)
          break;
        case "blankTextComment":
        case "mergedImageComment":
        case "mergedTextComment":
          this.detail.q_htext = text
          let mergedNote = this.note
          mergedNote.excerptText = text
          break;
        default:
          MNUtil.showHUD("Unsupported comment type: " + this.type)
          break;
      }
    }else{
      MNUtil.showHUD("No originalNoteId")
    }
  }
  get tags(){
    if (this.type === "tagComment") {
      return this.detail.text.split(/\s+/).filter(k => k.startsWith("#"))
    }
    return undefined
  }
  get direction(){
    if (this.type === "linkComment") {
      return this.linkDirection
    }
    return undefined
  }
  set direction(direction){
    if (this.type === "linkComment") {
      switch (direction) {
        case "one-way":
          this.removeBackLink()
          break;
        case "both":
          this.addBackLink()
          break;
        default:
          MNUtil.showHUD("Invalid direction: "+direction)
          break;
      }
    }
  }
  get note(){
    switch (this.type) {
      case "linkComment":
        return MNNote.new(this.detail.text)
      case "blankTextComment":
      case "blankImageComment":
      case "mergedImageCommentWithDrawing":
      case "mergedImageComment":
      case "mergedTextComment":
        return MNNote.new(this.detail.noteid)
      default:
        MNUtil.showHUD("No available note")
        return undefined
    }
  }
  refresh(){
    if (this.originalNoteId && this.index !== undefined) {
      let note = MNNote.new(this.originalNoteId)
      let comment = note.comments[this.index]
      this.type = MNComment.getCommentType(comment)
      this.detail = comment
    }
  }
  copyImage(){
    MNUtil.copyImage(this.imageData)
  }
  copyText(){
    MNUtil.copy(this.detail.text)
  }
  copy(){
    switch (this.type) {
      case "blankImageComment":
      case "mergedImageCommentWithDrawing":
      case "mergedImageComment":
        MNUtil.copyImage(MNUtil.getMediaByHash(this.detail.q_hpic.paint))
        break;
      case "drawingComment":
      case "imageCommentWithDrawing":
      case "imageComment":
        MNUtil.copyImage(MNUtil.getMediaByHash(this.detail.paint))
        break;
      case "blankTextComment":
      case "mergedTextComment":
        MNUtil.copy(this.detail.q_htext)
        break;
      default:
        MNUtil.copy(this.detail.text)
        break;
    }
  }
  remove(){
    if (this.originalNoteId) {
      let note = MNNote.new(this.originalNoteId)
      note.removeCommentByIndex(this.index)
    }else{
      MNUtil.showHUD("No originalNoteId")
    }
  }
  replaceLink(note){
    try {
    if (this.type === "linkComment" && note){
      let targetNote = MNNote.new(note)
      let currentNote = MNNote.new(this.originalNoteId)
      if (this.linkDirection === "both") {
        this.removeBackLink()//先去除原反链
        this.detail.text = targetNote.noteURL
        currentNote.replaceWithTextComment(this.detail.text,this.index)
        this.addBackLink(true)
      }else{
        this.detail.text = targetNote.noteURL
        currentNote.replaceWithTextComment(this.detail.text,this.index)
      }
    }
      } catch (error) {
      MNComment.addErrorLog(error, "replaceLink")
    }
  }
  hasBackLink(){
    if (this.type === "linkComment"){
      let fromNote = MNNote.new(this.originalNoteId)
      let toNote = this.note
      if (toNote.linkedNotes && toNote.linkedNotes.length > 0) {
        if (toNote.linkedNotes.some(n=>n.noteid === fromNote.noteId)) {
          return true
        }
      }
      return false
    }
    return false
  }
  removeBackLink(){
    if (this.type === "linkComment" && this.linkDirection === "both") {
      let targetNote = this.note//链接到的卡片
      if (this.hasBackLink()) {
        MNComment.from(targetNote).forEach(comment => {
          if (comment.type === "linkComment" && comment.note.noteId === this.originalNoteId) {
            comment.remove()
            this.linkDirection = "one-way"
          }
        })
      }
    }
  }
  addBackLink(force = false){
  try {
    if (this.type === "linkComment" && (this.linkDirection === "one-way" || force)) {
      let targetNote = this.note//链接到的卡片
      if (!this.hasBackLink()) {
        targetNote.appendNoteLink(this.originalNoteId,"To")
        this.linkDirection = "both"
      }
    }
  } catch (error) {
    MNComment.addErrorLog(error, "addBackLink")
  }
  }
  /**
   * 
   * @param {string[]} types 
   * @returns {boolean}
   */
  belongsToType(types){
    if (types.includes(this.detail.type)) {
      return true
    }
    if (types.includes(this.type)) {
      return true
    }
    return false
  }
  /**
   * 
   * @param {NoteComment} comment 
   * @param {string[]} types 
   * @returns {boolean}
   */
  static commentBelongsToType(comment,types){
    if (types.length === 0) {
      return false
    }
    if (types.includes(comment.type)) {
      return true
    }
    let newType = MNComment.getCommentType(comment)
    if (types.includes(newType)) {
      return true
    }
    return false
  }
  /**
   * 
   * @param {NoteComment} comment 
   * @returns {string}
   */
  static getCommentType(comment){
    switch (comment.type) {
      case "TextNote":
        if (/^#\S/.test(comment.text)) {
          return "tagComment"
        }
        if (/^marginnote\dapp:\/\/note\//.test(comment.text)) {
          //概要卡片的评论链接格式:marginnote4app://note/898B40FE-C388-4F3E-B267-C6606C37046C/summary/0
          if (/summary/.test(comment.text)) {
            return "summaryComment"
          }
          return "linkComment"
        }
        if (/^marginnote\dapp:\/\/note\//.test(comment.text)) {
          return "linkComment"
        }
        if (comment.markdown) {
          return "markdownComment"
        }
        return "textComment"
      case "HtmlNote":
        return "HtmlComment"
      case "LinkNote":
        if (comment.q_hblank) {
          let imageData = MNUtil.getMediaByHash(comment.q_hpic.paint)
          let imageSize = UIImage.imageWithData(imageData).size
          if (imageSize.width === 1 && imageSize.height === 1) {
            return "blankTextComment"
          }else{
            return "blankImageComment"
          }
        }
        if (comment.draft) {
          return "mergedChildMapComment"
        }
        if (comment.q_hpic) {
          if (comment.q_hpic.drawing) {
            return "mergedImageCommentWithDrawing"
          }
          return "mergedImageComment"
        }else{
          return "mergedTextComment"
        }
      case "PaintNote":
        if (comment.drawing) {
          if (comment.paint) {
            return "imageCommentWithDrawing"
          }else{
            return "drawingComment"
          }
        }else{
          return "imageComment"
        }
      case "AudioNote"://录音文件（可能还有其他的）
        return "audioComment"
      default:
        return undefined
    }
  }
  /**
   * 
   * @param {MNNote|MbBookNote} note
   * @returns {MNComment[]}
   */
  static from(note){
    if (!note) {
      MNUtil.showHUD("❌ No note found")
      return undefined
    }
    try {
      let newComments = note.comments.map((c,ind)=>MNComment.new(c,ind,note))
      return newComments
    } catch (error) {
      MNUtil.showHUD(error)
      return undefined
    }
  }
  /**
   * 
   * @param {NoteComment} comment 
   * @param {number|undefined} index 
   * @param {MbBookNote|undefined} note
   * @returns {MNComment}
   */
  static new(comment,index,note){
    try {
      
      let newComment = new MNComment(comment)
      if (note) {
        newComment.originalNoteId = note.noteId
      }
      if (index !== undefined) {
        newComment.index = index
      }
      if (newComment.type === 'linkComment') {
        if (newComment.hasBackLink()) {
          newComment.linkDirection = "both"
        }else{
          newComment.linkDirection = "one-way"
        }
      }
      if (newComment.type === 'summaryComment') {
        newComment.fromNoteId = MNUtil.extractMarginNoteLinks(newComment.detail.text)[0].replace("marginnote4app://note/","")
      }
        

      return newComment
    } catch (error) {
      this.addErrorLog(error, "new")
      return undefined
    }
  }
  /**
   * 
   * @param {string} message 
   * @param {any} detail 
   * @param {["INFO","ERROR","WARNING","DEBUG"]} level 
   */
  static log(message,detail,level = "INFO"){
    if (typeof MNLog !== "undefined") {
      MNLog.log({message:message,detail:detail,source:"MNComment",level:level})
      return
    }
    MNUtil.log({message:message,detail:detail,source:"MNComment",level:level})
  }
  static addErrorLog(error,source,info,showHUD = true){
    if (showHUD) {
      MNUtil.showHUD("MNComment Error ("+source+"): "+error)
    }
    let tem = {source:source,time:(new Date(Date.now())).toString()}
    if (error.detail) {
      tem.error = {message:error.message,detail:error.detail}
    }else{
      tem.error = error.message
    }
    if (info) {
      tem.info = info
    }
    MNUtil.errorLog.push(tem)
    MNUtil.copy(MNUtil.errorLog)
    if (typeof MNUtil.log !== 'undefined') {
      this.log({
        level:"error",
        message:source,
        detail:tem,
      })
    }
  }
}

class MNDocument{
  /** @type {MbBook} */
  document
  /**
   * 
   * @param {MbBook|string} document 
   */
  constructor(document){
    if (typeof document === "string") {
      this.document = MNUtil.getDocById(document)
    }else{
      this.document = document
    }
  }
  static cachedDocuments = {}
  /**
   * 
   * @param {string} message 
   * @param {any} detail 
   * @param {["INFO","ERROR","WARNING","DEBUG"]} level 
   */
  static log(message,detail,level = "INFO"){
    if (typeof MNLog !== "undefined") {
      MNLog.log({message:message,detail:detail,source:"MNNote",level:level})
      return
    }
    MNUtil.log({message:message,detail:detail,source:"MNDocument",level:level})
  }
  static addErrorLog(error,source,info,showHUD = true){
    if (showHUD) {
      MNUtil.showHUD("MNDocument Error ("+source+"): "+error)
    }
    let tem = {source:source,time:(new Date(Date.now())).toString()}
    if (error.detail) {
      tem.error = {message:error.message,detail:error.detail}
    }else{
      tem.error = error.message
    }
    if (info) {
      tem.info = info
    }
    MNUtil.errorLog.push(tem)
    MNUtil.copy(MNUtil.errorLog)
    if (typeof MNUtil.log !== 'undefined') {
      this.log({
        level:"error",
        message:source,
        detail:tem,
      })
    }
  }
  /**
   * 
   * @param {MbBook|string} document 
   * @returns {MNDocument}
   */
  static new(document){
    let type = MNUtil.typeOf(document)
    let docMd5 = undefined
    switch (type) {
      case "DocumentURL":
        docMd5 = MNUtil.parseURL(document).pathComponents[0]
        break;
      case "PageURL":
        docMd5 = MNUtil.parseURL(document).pathComponents[0]
        break;
      case "string":
        docMd5 = document
        break;
      case "MNDocument":
        docMd5 = document.docMd5
        break;
      default:
        break;
    }
    if (docMd5) {
      if (this.cachedDocuments[docMd5]) {//对于相同的document，只创建一个实例
        return this.cachedDocuments[docMd5]
      }
      let instance = new MNDocument(docMd5)
      if (instance.document) {
        this.cachedDocuments[docMd5] = instance
      }
      return instance
    }
    if (document.docMd5) {
      if (this.cachedDocuments[document.docMd5]) {//对于相同的document，只创建一个实例
        return this.cachedDocuments[document.docMd5]
      }
      let instance = new MNDocument(document)
      this.cachedDocuments[document.docMd5] = instance
      return instance
    }
    return new MNDocument(document)
  }
  static get currentDocument() {
    return MNDocument.new(MNUtil.currentDocmd5)
  }
  get docMd5(){
    if (!this.document) {
      return undefined
    }
    return this.document.docMd5
  }
  get md5(){
    if (!this.document) {
      return undefined
    }
    return this.document.docMd5
  }
  get id(){
    if (!this.document) {
      return undefined
    }
    return this.document.docMd5
  }
  get docTitle(){
    if (!this.document) {
      return undefined
    }
    return this.document.docTitle
  }
  get title(){
    if (!this.document) {
      return undefined
    }
    return this.document.docTitle
  }
  get pageCount(){
    if (!this.document) {
      return undefined
    }
    return this.document.pageCount
  }

  get fullPathFileName(){
    if (!this.document) {
      return undefined
    }
    return this.document.fullPathFileName
  }
  get path(){
    if (!this.document) {
      return undefined
    }
    return this.document.fullPathFileName
  }
  get fileData(){
    if (!this.document) {
      return undefined
    }
    return MNUtil.getFile(this.document.fullPathFileName)
  }
  get lastVisit(){
    if (!this.document) {
      return undefined
    }
    return this.document.lastVisit
  }
  get currentTopicId(){
    if (!this.document) {
      return undefined
    }
    return this.document.currentTopicId
  }
  get currentNotebookId(){
    if (!this.document) {
      return undefined
    }
    return this.document.currentTopicId
  }
  get currentNotebook(){
    if (!this.document) {
      return undefined
    }
    return MNNotebook.new(this.document.currentTopicId)
  }

  /**
   * 提取文件的数据，支持指定页码
   * @param {number[]} pageIndices 指定页码的数组，如果为空，则返回整个文件的数据
   * @returns {NSData}
   */
  getFileDataAtPages(pageIndices){
    if (pageIndices && pageIndices.length > 0) {
      if (MNUtil.isfileExists(this.fullPathFileName)) {
        let data = MNDocument.extractPDFPage(this.fullPathFileName, pageIndices)
        return data
      }
      return undefined
    }
    return undefined
  }
  /**
   * 缓存内容,key为pageNo,value为内容
   * @type {DictObj}
   */
  cacheContent = {}
  textContentsForPageNo(pageNo){
    return this.document.textContentsForPageNo(pageNo)
  }
  /**
   * 
   * @param {number} pageNo 
   * @param {boolean} cache 是否缓存内容，默认缓存，即如果缓存中存在，则直接返回缓存中的内容，如果cache为false，则不缓存，即每次都重新获取内容
   * @returns {string}
   */
  getPageContent(pageNo,cache = true){
    if (cache && this.cacheContent[pageNo]) {
      return this.cacheContent[pageNo]
    }
    let pageContent = MNUtil.getPageContent(pageNo,this.document)
    if (cache) {
      this.cacheContent[pageNo] = pageContent
    }
    return pageContent
  }
  /**
   * 
   * @param {boolean} asArray 是否返回数组，方便按页处理
   * @param {boolean} cache 是否缓存内容
   * @returns {string|string[]}
   */
  getFileContent(asArray = false,cache = true){
    let fileContent = []
    for (let pageNo = 1; pageNo <= this.pageCount; pageNo++) {
      fileContent.push(this.getPageContent(pageNo,cache))
    }
    return asArray ? fileContent : fileContent.join("\n")
  }
  open(notebookId){
    MNUtil.openDoc(this.docMd5,notebookId)
  }
  async openAtPage(pageNo,notebookId){
    if (this.docMd5 !== MNUtil.currentDocMd5) {
      MNUtil.openDoc(this.docMd5,notebookId)
      if (MNUtil.docMapSplitMode === 0) {
        MNUtil.docMapSplitMode = 1
      }
      await MNUtil.delay(0.01)
    }
    let docController = MNUtil.currentDocController
    let pageIndex = docController.indexFromPageNo(pageNo)
    if (docController.currPageIndex !== pageIndex) {
      docController.setPageAtIndex(pageIndex)
    }
  }
  get tocNotes(){
    return MNUtil.findToc(this.docMd5)
  }

  get documentNotebooks(){
    let allDocumentNotebooks = MNUtil.allDocumentNotebooks()
    return allDocumentNotebooks.filter(notebook=>notebook.mainDocMd5 === this.docMd5).map(notebook=>MNNotebook.new(notebook))
  }
  get studySets(){
    let allStudySets = MNUtil.allStudySets()
    return allStudySets.filter(notebook=>notebook.documents.some(doc=>doc.docMd5 === this.docMd5)).map(notebook=>MNNotebook.new(notebook))
  }
  get info(){
    if (!this.document) {
      return {
        fileExists:false,
        name:"",
        path:"",
        docURL: "marginnote4app://book/"+md5,
        md5:md5,
        type:"document"
      }
    }
    let fileInfo = {
      pageCount: this.pageCount,
      docURL: "marginnote4app://book/"+this.docMd5,
      file_type: "application/pdf",
      type: "file",
      title: this.docTitle,
      docId: this.docMd5,
      md5: this.docMd5
    }
    if (this.currentTopicId) {
      fileInfo.currentNotebook = {
        id:this.currentTopicId,
        name:MNUtil.getNoteBookById(this.currentTopicId).title,
      }
    }
    if (this.fullPathFileName) {
      fullPath = this.fullPathFileName
    }else{
      let folder = MNUtil.documentFolder
      fullPath = folder+"/"+this.document.pathFile
      if (this.document.pathFile.startsWith("$$$MNDOCLINK$$$")) {
        let fileName = MNUtil.getFileName(this.pathFile)
        fullPath = MNUtil.tempFolder + fileName
      }
    }
    fileInfo.path = fullPath
    fileInfo.fileExists = MNUtil.isfileExists(fileInfo.path)
    return fileInfo
  }
  get fileExists(){
    if (this.fullPathFileName) {
      return MNUtil.isfileExists(this.fullPathFileName)
    }
    return false
  }
  documentNotebookInStudySet(notebookId = MNUtil.currentNotebookId){
    let notebook = MNNotebook.new(notebookId)
    if (notebook.type === "studySet") {//仅在学习集中可用
      let options = notebook.options
      if (options && options.bookGroupNotes) {
        let bookGroupNotes = options.bookGroupNotes
        if (this.docMd5 in bookGroupNotes) {
          return MNNotebook.new(bookGroupNotes[this.docMd5].notebookId)
        }
      }
    }
    if (notebook.type === "documentNotebook") {
      return notebook
    }
    return undefined
  }
  notesInDocumentInStudySet(notebookId = MNUtil.currentNotebookId){
    let notebook = this.documentNotebookInStudySet(notebookId)
    return notebook.notes
  }
  // associatedTopicsInNotebook(notebookId = MNUtil.currentNotebookId){
  //   let notebook = MNNotebook.new(notebookId)
  //   let options = notebook.options
  //   if (options && options.associatedTopics) {
  //     let associatedTopics = options.associatedTopics
  //     if (this.docMd5 in associatedTopics) {
  //       return associatedTopics[this.docMd5].map(topicId=>MNNotebook.new(topicId))
  //     }
  //   }
  //   return []
  // }
  mainNoteInNotebook(notebookId = MNUtil.currentNotebookId){
    let notebook = MNNotebook.new(notebookId)
    if (notebook.type === "studySet") {
      return notebook.mainNoteForDoc(this.docMd5)
    }
    return undefined
  }
  // get reviewGroups(){
  //   let allReviewGroups = MNUtil.allReviewGroups()
  //   return allReviewGroups.filter(notebook=>notebook.mainDocMd5 === this.docMd5).map(notebook=>MNNotebook.new(notebook))
  // }
  copy(){
    let docInfo = {
      id:this.docMd5,
      currentNotebookId:this.currentTopicId,
      title:this.docTitle,
      pageCount:this.pageCount,
      path:this.fullPathFileName
    }
    MNUtil.copy(docInfo)
  }
  /**
   * 
   * @param {string} path
   * @param {number[]} targetPageIndices
   * @returns {Promise<NSData>}
   */
  static async extractPDFPage(path,targetPageIndices){
  try {
    let file = MNUtil.getFile(path)
    let sourceBase64 = file.base64Encoding()
    let newBase64 = await PDFTools.extractPage(sourceBase64, targetPageIndices)
    let data = MNUtil.dataFromBase64(newBase64,"pdf")
    return data
  } catch (error) {
    this.addErrorLog(error,"extractPDFPage")
    return undefined
  }
  }
}
class MNNotebook{
  /** @type {MbTopic} */
  notebook
  /**
   * 
   * @param {MbTopic|string} notebook 
   */
  constructor(notebook){
    switch (MNUtil.typeOf(notebook)) {
      case "NotebookURL":
        this.notebook = MNUtil.getNoteBookById(MNUtil.getNotebookIdByURL(notebook))
        break;
      case "NoteId":
        this.notebook = MNUtil.getNoteBookById(notebook)
        break;
      default:
        this.notebook = notebook
        break;
    }
  }
  /**
   * 
   * @param {MbTopic} notebook 
   * @returns {MNNotebook}
   */
  static new(notebook){
    switch (MNUtil.typeOf(notebook)) {
      case "MNNotebook":
        return notebook
      case "NoteId":
        let temNotebook = MNUtil.getNoteBookById(notebook)
        if (temNotebook) {
          return new MNNotebook(temNotebook)
        }else{
          if (MNUtil.getNoteById(notebook,false)) {
            let note = MNUtil.getNoteById(notebook)
            return new MNNotebook(note.notebookId)
          }
        }
        return undefined
      default:
        break
    }
    if (notebook.topicId) {
      return new MNNotebook(notebook)
    }
    return undefined
  }
  static get currentNotebook() {
    return MNNotebook.new(MNUtil.currentNotebookId)
  }

  static allNotebooks(){
    return MNUtil.allNotebooks().map(notebook=>MNNotebook.new(notebook))
  }
  static allNotebookIds(){
    return MNUtil.allNotebookIds()
  }
  static allDocumentNotebooks(option = {}){
    let documentNotebooks = MNUtil.allDocumentNotebooks(option)
    return documentNotebooks.map(notebook=>MNNotebook.new(notebook))
  }
  static allReviewGroups(option = {}){
    let reviewGroups = MNUtil.allReviewGroups(option)
    return reviewGroups.map(notebook=>MNNotebook.new(notebook))
  }
  static allStudySets(option = {}){
  try {
    let exceptNotebookIds = option.exceptNotebookIds ?? []
    let exceptNotebookNames = option.exceptNotebookNames ?? []
    let studySets = this.allNotebooks().filter(notebook=>{
      let flags = notebook.flags
      if (flags === 2) {
        if (exceptNotebookIds.length > 0 || exceptNotebookNames.length > 0) {
          if (exceptNotebookIds.includes(notebook.topicId)) {
            return false
          }
          if (exceptNotebookNames.includes(notebook.title.trim())) {
            return false
          }
        }
        return true
      }
      return false
    })
    return studySets
    
  } catch (error) {
    this.addErrorLog(error, "allStudySets")
    return []
  }
  }
  get notebookId(){
    return this.notebook.topicId
  }
  get topicId(){
    return this.notebook.topicId
  }
  get id(){
    return this.notebook.topicId
  }
  get title(){
    return this.notebook.title
  }
  get flags(){
    return this.notebook.flags
  }
  get noteColors(){
    MNUtil.getNotebookExcerptColorById(this.notebookId)
  }
  /**
   * 
   * @returns {"documentNotebook"|"studySet"|"reviewGroup"|"unknown"}
   */
  get type(){
    switch (this.notebook.flags) {
      case 1:
        return "documentNotebook"
      case 2:
        return "studySet"
      case 3:
        return "reviewGroup"
      default:
        return "unknown"
    }
  }
  get url(){
    return "marginnote4app://notebook/"+this.notebook.topicId
  }
  get mainDocMd5(){
    return this.notebook.mainDocMd5
  }
  get mainDoc(){
    return MNUtil.getDocById(this.notebook.mainDocMd5)
  }
  /**
   * 
   * @returns {MNNote[]}
   */
  get notes(){
    if (this.type === "studySet") {
      return this.notebook.notes.filter(note=>!note.docMd5.endsWith("_StudySet")).map(note=>MNNote.new(note))
    }
    return this.notebook.notes?.map(note=>MNNote.new(note)) ?? []
  }
  /**
   * 
   * @returns {MbBook[]}
   */
  get documents(){
    return this.notebook.documents
  }
  /**
   * 
   * @returns {MbBook[]}
   */
  get documentIds(){
    return this.notebook.docList?.split("|")
  }
  /**
   * 
   * @returns {DictObj}
   */
  get options(){
    return this.notebook.options
  }
  /**
   * 
   * @returns {string}
   */
  get hashtags(){
    return this.notebook.hashtags
  }
  /**
   * 
   * @returns {string[]}
   */
  get tags(){
    return this.notebook.hashtags?.split("#")?.filter(k=>k.trim()) ?? []
  }
  get tagsTree(){
    let tags = this.hashtags.split(" ")
    let tagsTree = MNUtil.parseTagsToTree(tags)
    return tagsTree
  }
  /**
   * 
   * @param {boolean} hide 
   */
  set hideLinksInMindMapNode(hide){
    this.notebook.hideLinksInMindMapNode = hide
  }
  /**
   * 
   * @returns {boolean}
   */
  get hideLinksInMindMapNode(){
    return this.notebook.hideLinksInMindMapNode
  }
  /**
   * 
   * @returns {MNNotebook|undefined}
   */
  get reviewGroup(){
    let options = this.notebook.options
    if (options && options.reviewTopic) {
      return MNNotebook.new(options.reviewTopic)
    }
    return undefined
  }
  /**
   * 
   * @returns {MbBook[]}
   */
  get tabDocuments(){
    let options = this.notebook.options
    if (options) {
      let md5List = options.tabMd5Lst.split("|")
      return md5List.map(md5=>MNUtil.getDocById(md5))
    }
    return []
  }
  /**
   * 
   * @returns {MNNote|undefined}
   */
  get focusedChat(){
    let options = this.notebook.options
    if (options && options.FocusChatId) {
      return MNNote.new(options.FocusChatId)
    }
    return undefined
  }
  /**
   * 
   * @param {string} docMd5 
   * @returns {MNNotebook[]|undefined}
   */
  notebooksForDoc(docMd5 = MNUtil.currentDocmd5){
    let options = this.notebook.options
    if (options && options.associatedTopics) {
      let associatedTopics = options.associatedTopics
      if (docMd5 in associatedTopics) {
        let topicIds = associatedTopics[docMd5]
        if (topicIds.length) {
          return topicIds.map(topicId=>MNNotebook.new(topicId))
        }
      }
    }
    return undefined
  }
  /**
   * 
   * @param {string} docMd5 
   * @returns {MNNote|undefined}
   */
  mainNoteForDoc(docMd5 = MNUtil.currentDocmd5){
    let options = this.notebook.options
    if (options && options.bookGroupNotes) {
      let bookGroupNotes = options.bookGroupNotes
      if (docMd5 in bookGroupNotes) {
        return MNNote.new(bookGroupNotes[docMd5].noteid)
      }
      return undefined
    }
    return undefined
  }

  tocNotesForDoc(docMd5 = MNUtil.currentDocmd5){
    let options = this.notebook.options
    if (options && options.bookGroupNotes) {
      let bookGroupNotes = options.bookGroupNotes
      if (docMd5 in bookGroupNotes) {
        let tocNoteIds = bookGroupNotes[docMd5].tocNoteIds
        if (tocNoteIds) {
          return tocNoteIds.map(noteId=>MNNote.new(noteId))
        }
      }
    }
    return []
  }
  open(){
    MNUtil.openNotebook(this.id)
  }
  openDoc(docMd5){
    MNUtil.openDoc(docMd5,this.id)
  }
  importDoc(){
    MNUtil.importPDFFromFileAndOpen(this.id)
  }
  copy(){
    let notebookInfo = {
      id:this.id,
      title:this.title,
      type:this.type,
      url:this.url,
      mainDocMd5:this.mainDocMd5
    }
    MNUtil.copy(notebookInfo)
  }
}
