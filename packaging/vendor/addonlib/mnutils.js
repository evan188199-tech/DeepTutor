if (typeof setTimeout === "undefined") {
  // 直接挂载到 globalContext，确保第三方库能访问到
  /**
   * 设置定时器
   * @param {function} callback 
   * @param {number} delay 延时时间，单位为毫秒或秒，阈值为50
   * @returns {number} 定时器ID
   */
  globalThis.setTimeout = function(callback, delay) {
    
    // 防止 delay 为空或非数字
    var seconds = delay || 0;

    if (seconds > 50) {
      //防呆设计，阈值为50，如果delay为1，则视为1秒，如果为100时，视为100ms
      seconds = seconds/1000.
    }
    
    // 调用原生层 (假设你的 NSTimer 接口是这样用的)
    // 注意：这里不需要 return new Promise，也不需要 async
    let timer = NSTimer.scheduledTimerWithTimeInterval(seconds, false, function () {
        // 执行回调
        if (typeof callback === 'function') {
            callback();
        } else if (typeof callback === 'string') {
            // 兼容极少数库传字符串的情况 (不推荐但存在)
            try { eval(callback); } catch(e){}
        }
    });

    // 标准 setTimeout 会返回一个整数 ID 用于 clearTimeout
    // 这里我们随便返回一个数字，防止库报错
    let timerId = MNUtil.addTimer(timer);
    return timerId;
  };
  /**
   * 设置定时器
   * @param {function} callback 
   * @param {number} interval 间隔时间，单位为毫秒或秒，阈值为50
   * @returns {number} 定时器ID
   */
  globalThis.setInterval = function(callback, interval) {
    // 防止 delay 为空或非数字
    var seconds = interval || 0;
    if (seconds > 50) {
      //防呆设计，阈值为50，如果interval为1，则视为1秒，如果为100时，视为100ms
      seconds = seconds/1000.
    }
    // 调用原生层 (假设你的 NSTimer 接口是这样用的)
    // 注意：这里不需要 return new Promise，也不需要 async
    let timer = NSTimer.scheduledTimerWithTimeInterval(seconds, true, function () {
        // 执行回调
        if (typeof callback === 'function') {
            callback();
        } else if (typeof callback === 'string') {
            // 兼容极少数库传字符串的情况 (不推荐但存在)
            try { eval(callback); } catch(e){}
        }
    });

    // 标准 setTimeout 会返回一个整数 ID 用于 clearTimeout
    // 这里我们随便返回一个数字，防止库报错
    let timerId = MNUtil.addTimer(timer);
    return timerId;
  };
  // 3. 最好顺手把 clearTimeout 也补上，防止报错
  if (typeof clearTimeout === "undefined") {
    globalThis.clearTimeout = function(id) {
      // 如果原生没有提供取消 Timer 的接口，这里留空即可
      // 至少保证库调用它时不会崩溃
      MNUtil.clearTimer(id);

    };
  }
  if (typeof clearInterval === "undefined") {
    globalThis.clearInterval = function(id) {
      MNUtil.clearTimer(id);
    };
  }
  if (typeof atob === "undefined") {
    globalThis.atob = function(str) {
      return DataConverter.atob(str)
    };
  }
}

class Mustache {
  /**
   * 
   * @param {string} template 
   * @param {object} config 
   * @returns {string}
   */
  static render(template,config){
    let output = mustache.render(template,config)
    return output
  }
  /**
   * 
   * @param {string} template 
   * @returns {Array<{type:string,value:string,start:number,end:number}>}
   */
  static parse(template){
    return mustache.parse(template)
  }
}

class Locale{
  static init(mainPath){
  try {
    this.mainPath = mainPath
    this.current = NSLocale.currentLocale()
    this.isZH = this.current.localeIdentifier().startsWith("zh")
    this.isEN = this.current.localeIdentifier().startsWith("en")
    this._ZHConfig = this.readJSON(this.mainPath+"/data/zh.json")
    this._ENConfig = this.readJSON(this.mainPath+"/data/en.json")
    this.cancelString = this.getLocalNameForKey("cancel")
    this.confirmString = this.getLocalNameForKey("confirm")
    this.language = this.isZH ? "zh" : "en"
  } catch (error) {
    this.copy(error.message)
  }
  }
  static copy(message){
    UIPasteboard.generalPasteboard().string = message
  }
  static addZHConfig(config){
    this._ZHConfig = {...this._ZHConfig, ...config}
  }
  static addENConfig(config){
    this._ENConfig = {...this._ENConfig, ...config}
  }
  /**
   * 
   * @param {string} path 
   * @returns {boolean}
   */
  static isfileExists(path) {
    return NSFileManager.defaultManager().fileExistsAtPath(path)
  }
  /**
   * 
   * @param {string} path 
   * @returns {object|undefined}
   */
  static readJSON(path){
    if (!this.isfileExists(path)) {
      return undefined
    }
    let data = NSData.dataWithContentsOfFile(path)
    const res = NSJSONSerialization.JSONObjectWithDataOptions(
      data,
      1<<0
    )
    if (NSJSONSerialization.isValidJSONObject(res)) {
      return res
    }else{
      return undefined
    }
  }
  static get preferredLanguages(){
    return NSLocale.preferredLanguages()
  }
  static getZHNameForKey(key){
  try {
    if (this._ZHConfig === undefined) {
      this._ZHConfig = this.readJSON(this.mainPath+"/data/zh.json")
    }
    if (key in this._ZHConfig) {
      return this._ZHConfig[key]
    }else{
      return this.getENNameForKey(key)
    }
    
  } catch (error) {
    // this.addErrorLog(error, "Locale.getZHNameForKey",this.mainPath+"/data/zh.json")
    return key
  }
  }
  static getENNameForKey(key){
    if (this._ENConfig === undefined) {
      this._ENConfig = this.readJSON(this.mainPath+"/data/en.json")
    }
    if (key in this._ENConfig) {
      return this._ENConfig[key]
    }else{
      return key
    }
  }
  static getLocalNameForKey(key){
    try {
      if (this.isZH) {
        return this.getZHNameForKey(key)
      }else{
        return this.getENNameForKey(key)
      }
    } catch (error) {
      this.copy(error.message)
      return key
    }
  }
  static at(key){
    try {
      if (this.isZH) {
        return this.getZHNameForKey(key)
      }else{
        return this.getENNameForKey(key)
      }
    } catch (error) {
      this.copy(error.message)
      return key
    }
  }
  /**
   * 渲染模板
   * @param {string} template 
   * @returns {string}
   */
  static render(template,additionalConfig = {}){
  try {
    if (this.isZH) {
      return MNUtil.render(template, {...this._ZHConfig, ...additionalConfig})
    }else{
      return MNUtil.render(template, {...this._ENConfig, ...additionalConfig})
    }
  } catch (error) {
    this.copy(error.message)
    return template
  }
  }
  static showHUD(message,additionalConfig = {}){
    let renderedMessage = this.render(message,additionalConfig)
    MNUtil.showHUD(renderedMessage)
  }
}

if (typeof Frame === "undefined") {
  class Frame{
    static gen(x,y,width,height){
      return MNUtil.genFrame(x, y, width, height)
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} x 
     * @param {number} y 
     * @param {number} width 
     * @param {number} height 
     */
    static set(view,x,y,width,height){
      let oldFrame = view.frame
      let frame = view.frame
      if (x !== undefined) {
        frame.x = x
      }else if (view.x !== undefined) {
        frame.x = view.x
      }
      if (y !== undefined) {
        frame.y = y
      }else if (view.y !== undefined) {
        frame.y = view.y
      }
      if (width !== undefined) {
        frame.width = width
      }else if (view.width !== undefined) {
        frame.width = view.width
      }
      if (height !== undefined) {
        frame.height = height
      }else if (view.height !== undefined) {
        frame.height = view.height
      }
      if (!this.sameFrame(oldFrame,frame)) {
        view.frame = frame
      }
    }
    static sameFrame(frame1,frame2){
      if (frame1.x === frame2.x && frame1.y === frame2.y && frame1.width === frame2.width && frame1.height === frame2.height) {
        return true
      }
      return false
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} x
     */
    static setX(view,x){
      let frame = view.frame
      frame.x = x
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} y
     */
    static setY(view,y){
      let frame = view.frame
      frame.y = y
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view
     * @param {number} x 
     * @param {number} y 
     */
    static setLoc(view,x,y){
      let frame = view.frame
      frame.x = x
      frame.y = y
      if (view.width) {
        frame.width = view.width
      }
      if (view.height) {
        frame.height = view.height
      }
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} width 
     * @param {number} height 
     */
    static setSize(view,width,height){
      let frame = view.frame
      frame.width = width
      frame.height = height
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} width
     */
    static setWidth(view,width){
      let frame = view.frame
      frame.width = width
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} height
     */
    static setHeight(view,height){
      let frame = view.frame
      frame.height = height
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} xDiff
     */
    static moveX(view,xDiff){
      let frame = view.frame
      frame.x = frame.x+xDiff
      view.frame = frame
    }
    /**
     * 
     * @param {UIView} view 
     * @param {number} yDiff
     */
    static moveY(view,yDiff){
      let frame = view.frame
      frame.y = frame.y+yDiff
      view.frame = frame
    }
  }
  globalThis.Frame = Frame
}
class Menu{
  /**
   * 左 0, 下 1，3, 上 2, 右 4
   * @type {number}
   */
  preferredPosition = 2
  /**
   * @type {string[]}
   */
  titles = []
  constructor(sender,delegate,width = undefined,preferredPosition = 2){
    this.menuController = MenuController.new()
    this.delegate = delegate
    this.sender = sender
    this.commandTable = []
    this.minWidth = 100
    this.maxHeight = 0
    this.menuController.rowHeight = 35
    this.preferredPosition = preferredPosition
    if (width && width >100) {//宽度必须大于100,否则不允许设置,即转为自动宽度
      this.width = width
    }
  }
  /**
   * 
   * @param {UIView|MNButton} sender 
   * @param {Object} delegate 
   * @param {number} width 
   * @param {number} preferredPosition 
   * @returns {Menu}
   */
  static new(sender,delegate,width = undefined,preferredPosition = 2){
    if (sender instanceof MNButton) {
      sender = sender.button
    }
    return new Menu(sender,delegate,width,preferredPosition)
  }
  /**
   * @param {object[]} items
   */
  set menuItems(items){
    this.commandTable = items
  }
  get menuItems(){
    return this.commandTable
  }
  /**
   * @param {number} height
   */
  set rowHeight(height){
    this.menuController.rowHeight = height
  }
  get rowHeight(){
    return this.menuController.rowHeight
  }
  /**
   * @param {number} size
   */
  set fontSize(size){
    this.menuController.fontSize = size
  }
  get fontSize(){
    return this.menuController.fontSize
  }
  addMenuItem(title,selector,params = "",checked=false){
    let typeOfTitle = typeof title
    if (typeOfTitle === "string") {
      this.commandTable.push({title:title,object:this.delegate,selector:selector,param:params,checked:checked})
      return
    }
    let key = title.key
    let localeTitle = Locale.getLocalNameForKey(key)
    if ("prefix" in title) {
      localeTitle = title.prefix  + localeTitle
    }
    if ("suffix" in title) {
      localeTitle = localeTitle  + title.suffix
    }
    this.commandTable.push({title:localeTitle,object:this.delegate,selector:selector,param:params,checked:checked})
  }
  addItem(title,selector,params = "",checked=false){
    let typeOfTitle = typeof title
    if (typeOfTitle === "string") {
      this.commandTable.push({title:title,object:this.delegate,selector:selector,param:params,checked:checked})
      return
    }
    let key = title.key
    let localeTitle = Locale.getLocalNameForKey(key)
    if ("prefix" in title) {
      localeTitle = title.prefix + localeTitle
    }
    if ("suffix" in title) {
      localeTitle = localeTitle + title.suffix
    }
    this.commandTable.push({title:localeTitle,object:this.delegate,selector:selector,param:params,checked:checked})
  }
  addMenuItems(items){
    let fullItems = items.map(item=>{
      if ("object" in item) {
        return item
      }else{
        item.object = this.delegate
        return item
      }
    })
    this.commandTable.push(...fullItems)
  }
  addItems(items){
    let fullItems = items.map(item=>{
      if ("object" in item) {
        return item
      }else{
        item.object = this.delegate
        return item
      }
    })
    this.commandTable.push(...fullItems)
  }
  insertMenuItem(index,title,selector,params = "",checked=false){
    this.commandTable.splice(index,0,{title:title,object:this.delegate,selector:selector,param:params,checked:checked})
  }
  insertMenuItems(index,items){
    let fullItems = items.map(item=>{
      if ("object" in item) {
        return item
      }else{
        item.object = this.delegate
        return item
      }
    })
    this.commandTable.splice(index,0,...fullItems)
  }
  show(autoWidth = false,animate = true){
  try {
    if (autoWidth || !this.width) {//用autoWidth参数来控制是否自动计算宽度,如果menu实例没有width参数,也会自动计算宽度
      let widths = this.commandTable.map(item=>{
        if (item.checked) {
          return MNUtil.strCode(item.title)*9+70
        }else{
          return MNUtil.strCode(item.title)*9+30
        }
      })
      this.width = Math.max(...widths)
      if (this.width < this.minWidth) {
        this.width = this.minWidth
      }
      // let titles = this.commandTable.map(item=>item.title)
      // let maxWidth = 0
      // // let maxWidth = this.width
      // titles.forEach(title=>{
      //   let width = MNUtil.strCode(title)*9+30
      //   if (width > maxWidth) {
      //     maxWidth = width
      //   }
      // })
      // this.width = maxWidth
    }

    let position = this.preferredPosition
    this.menuController.commandTable = this.commandTable
    let height = this.menuController.rowHeight * this.menuController.commandTable.length
    if (this.maxHeight > 50 && height > this.maxHeight) {
      height = this.maxHeight
    }
    this.menuController.preferredContentSize = {
      width: this.width,
      height: this.menuController.rowHeight * this.menuController.commandTable.length
    };
    // this.menuController.secHeight = 200
    // this.menuController.sections = [{title:"123",length:10,size:10,row:this.commandTable,rows:this.commandTable,cell:this.commandTable}]
    // this.menuController.delegate = this.delegate

    var popoverController = new UIPopoverController(this.menuController);
    let targetView = MNUtil.studyView
    var r = this.sender.convertRectToView(this.sender.bounds,targetView);
    switch (position) {
      case 0:
        if (r.x < 50) {
          position = 4
        }
        break;
      case 1:
      case 3:
        if (r.y+r.height > targetView.frame.height - 50) {
          position = 2
        }
        break;
      case 2:
        if (r.y < 50) {
          position = 3
        }
        break;
      case 4:
        if (r.x+r.width > targetView.frame.width - 50) {
          position = 0
        }
        break;
      default:
        break;
    }
    popoverController.presentPopoverFromRect(r, targetView, position, animate);
    popoverController.delegate = this.delegate
    // this.menuController.menuTableView.dataSource = this.delegate
    Menu.popover = popoverController
  } catch (error) {
    MNUtil.addErrorLog(error, "Menu.show")
  }
  }
  dismiss(){
    if (Menu.popover) {
      Menu.popover.dismissPopoverAnimated(true)
      Menu.popover = undefined
    }
  }
  static item(title,selector,params = "",checked=false){
    return {title:title,selector:selector,param:params,checked:checked}
  }
  static popover = undefined
  static dismissCurrentMenu(animate = true){
    if (this.popover) {
      this.popover.dismissPopoverAnimated(animate)
    }
  }
}



class MNUtil {
  /**
   * 是否正在显示alert
   * @type {boolean}
   */
  static onAlert = false
  static themeColor = {
    Gray: UIColor.colorWithHexString("#414141"),
    Default: UIColor.colorWithHexString("#FFFFFF"),
    Dark: UIColor.colorWithHexString("#000000"),
    Green: UIColor.colorWithHexString("#E9FBC7"),
    Sepia: UIColor.colorWithHexString("#F5EFDC")
  }
  /**
   * 缓存图片类型
   * {
   *  "xxxx": "png",
   *  "xxxx": "jpeg",
   * }
   */
  static imageTypeCache = {}
  static popUpNoteInfo = undefined;
  static popUpSelectionInfo = undefined;
  static mainPath
  static initialized = false

  /**
   * 数据文件夹,和插件位于同一个目录下
   */
  static dataFolder = ""
  static MNImagePattern = /!\[.*?\]\((marginnote4app\:\/\/markdownimg\/(png|jpeg)\/.*?)(\))/g;
  /**
   * @type {string}
   */
  static extensionPath
  static defaultNoteColors = ["#ffffb4","#ccfdc4","#b4d1fb","#f3aebe","#ffff54","#75fb4c","#55bbf9","#ea3323","#ef8733","#377e47","#173dac","#be3223","#ffffff","#dadada","#b4b4b4","#bd9fdc"]
  static init(mainPath){
    if (this.initialized) {
      return
    }
    this.dotBase64 = this.getFile(Runtime.assets.resolve("assets/dot.png")).base64Encoding()
    this.dotBytes = DataConverter.base64ToUint8Array(this.dotBase64)
    this.mainPath = Runtime.assets.resolve("")
    this.extensionPath = mainPath.replace(/\/marginnote\.extension\.\w+/,"")
    this.checkDataDir()
    this.initialized = true
  }
  static checkDataDir(){
    let extensionPath = this.extensionPath
    if (extensionPath) {
      let dataPath = extensionPath+"/data"
      if (this.isfileExists(dataPath)) {
        this.dataFolder = dataPath
        return
      }
      this.createFolderDev(dataPath)
      // NSFileManager.defaultManager().createDirectoryAtPathAttributes(dataPath, undefined)
      this.dataFolder = dataPath
    }
  }
  static _currentTimerId = 0
  /**
   * 定时器列表
   * {
   *  "xxxx": NSTimer,
   *  "xxxx": NSTimer,
   * }
   */
  static timers = {}
  /**
   * 添加定时器
   * 返回定时器ID
   * @returns {number}
   */
  static addTimer(timer){
    let timerId = MNUtil._currentTimerId++;
    let timerIdString = String(timerId);
    this.timers[timerIdString] = timer;
    return timerId;
  }
  /**
   * 清除定时器
   * @param {number} timerId 
   */
  static clearTimer(timerId){
    let timerIdString = String(timerId);
    if (this.timers[timerIdString]) {
      this.timers[timerIdString].invalidate();
      delete this.timers[timerIdString];
    }
  }
  /**
   * 只记录最近十次的操作
   * @type {Array<{type:string,time:number,noteId:string,text:string,imageData:NSData,notebookId:string,docMd5:string,pageIndex:number}>}
   */
  static focusHistory = []
  /**
   * 只记录最近十次的操作
   * @param {string} type
   * @param {{noteId:string,text:string,imageData:NSData,notebookId:string,docMd5:string}} detail 
   */
  static addHistory(type,detail){
    if (this.focusHistory.length>=10) {
      this.focusHistory.shift()
    }
    let history = {type:type,time:Date.now(),...detail}
    this.focusHistory.push(history)
    // MNUtil.copy(this.focusHistory)
  }
  static errorLog = []
  /**
   * 
   * @param {string|{message:string,level:string,source:string,timestamp:number,detail:string}} error 
   * @param {string} source 
   * @param {string} info 
   */
  static addErrorLog(error,source,info){
    MNUtil.showHUD("Runtime Error ("+source+"): "+error)
    let tem = {source:source,time:(new Date(Date.now())).toString()}
    if (typeof error === "string") {
      tem.error = error
    }else{
      if (error.detail) {
        tem.error = {message:error.message,detail:error.detail}
      }else{
        tem.error = error.message
      }
    }
    if (info) {
      tem.info = info
    }
    this.errorLog.push(tem)
    this.copyJSON(this.errorLog)
    this.log({
      message:source,
      level:"ERROR",
      source:"MN Utils",
      timestamp:Date.now(),
      detail:tem
    })
  }
static customBtoa(str) {
    var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
    var output = '';
    var idx = 0;
    
    // 确保输入是字符串
    str = String(str);
    
    while (idx < str.length) {
        // 每次读取 3 个字节
        var c1 = str.charCodeAt(idx++);
        var c2 = str.charCodeAt(idx++);
        var c3 = str.charCodeAt(idx++);

        // 将 3 个 8位字节 转换为 4 个 6位索引
        var e1 = c1 >> 2;
        // c1 的后2位 + c2 的前4位
        var e2 = ((c1 & 3) << 4) | (c2 >> 4);
        // c2 的后4位 + c3 的前2位
        var e3 = ((c2 & 15) << 2) | (c3 >> 6);
        // c3 的后6位
        var e4 = c3 & 63;

        // 处理填充逻辑 (=)
        // 如果 c2 是 NaN (也就是字符串结束了)，e3 和 e4 都应该是填充符
        if (isNaN(c2)) {
            e3 = e4 = 64; // 64 对应 chars 里的 '='
        } 
        // 如果 c3 是 NaN，e4 应该是填充符
        else if (isNaN(c3)) {
            e4 = 64;
        }

        output += chars.charAt(e1) + chars.charAt(e2) + chars.charAt(e3) + chars.charAt(e4);
    }
    
    return output;
}
static utf8_to_b64(str) {//备用
    // 第一步：使用 encodeURIComponent 将宽字符转换成 UTF-8 编码的百分号序列
    // 第二步：使用 replace 将百分号序列 (%XX) 还原为单字节字符
    var binaryStr = encodeURIComponent(str).replace(/%([0-9A-F]{2})/g,
        function(match, p1) {
            return String.fromCharCode('0x' + p1);
        });
    
    // 第三步：调用上面的基础版 btoa
    return this.customBtoa(binaryStr);
}

static customAtob(input) {
    var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
    var str = String(input).replace(/=+$/, ''); // 去除末尾的 padding
    var output = '';

    if (str.length % 4 == 1) {
        throw new Error("'atob' failed: The string to be decoded is not correctly encoded.");
    }

    for (var bc = 0, bs = 0, buffer, i = 0;
        buffer = str.charAt(i++);

        ~buffer && (bs = bc % 4 ? bs * 64 + buffer : buffer,
            // 累积满 24 bit (4个字符) 后，解码出 3个字节
            bc++ % 4) ? output += String.fromCharCode(255 & bs >> (-2 * bc & 6)) : 0
    ) {
        // 获取字符在索引表中的位置
        buffer = chars.indexOf(buffer);
    }

    return output;
}

// 支持中文的解码封装，备用
static b64_to_utf8(str) {
    // 1. 基础解码
    var binaryStr = customAtob(str);
    // 2. 将单字节字符还原回 %XX 格式
    var percentStr = binaryStr.split('').map(function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join('');
    // 3. 解析 URI 组件
    return decodeURIComponent(percentStr);
}
static btoa(str) {
  return this.customBtoa(str)
    // // Encode the string to a WordArray
    // const wordArray = CryptoJS.enc.Utf8.parse(str);
    // // Convert the WordArray to Base64
    // const base64 = CryptoJS.enc.Base64.stringify(wordArray);
    // return base64;
}
/**
 * 压缩配置,pako压缩效率高，但更消耗资源和时间,lz-string压缩效率低，但更节省资源和时间
 * @param {object} jsonObj - 要编码的 JSON 对象
 * @param {"pako"|"lz-string"} type - 压缩方式，pako或lz-string
 * @returns {string} - 生成的 Base64 字符串
 */
static compressAndEncode(jsonObj,type = "pako") {
  try {
    const jsonString = JSON.stringify(jsonObj);
    if (type == "pako") {
      // 1. Gzip 压缩 (得到 Uint8Array)
      const compressedUint8 = pako.gzip(jsonString);
      // 2. 将 Uint8Array 转换为 CryptoJS 的 WordArray
      const wordArray = CryptoJS.lib.WordArray.create(compressedUint8);
      // 3. Base64 编码
      const base64 = CryptoJS.enc.Base64.stringify(wordArray);
      return base64;
    }
    if (type == "lz-string") {
      const base64 = LZString.compressToBase64(jsonString);
      return base64;
    }
    
  } catch (error) {
    this.addErrorLog(error, "compressAndEncode")
    return undefined
  }
}
/**
 * 解码 Base64 字符串，并使用 gzip 解压
 * @param {string} base64 - 要解码的 Base64 字符串
 * @returns {string} - 解压后的字符串，如果是json字符串需要自行parse为对象
 */
static decodeAndDecompress(base64,type = "pako") {
  try {
    if (type == "pako") {
      let binaryString = this.atob(base64);
      // 将二进制字符串转换为 Uint8Array，这是 pako 需要的输入格式
      const charData = binaryString.split('').map(x => x.charCodeAt(0));
      const binData = new Uint8Array(charData);
      // 3. Gzip 解压
      // 使用 pako.ungzip 进行解压
      const decompressedData = pako.ungzip(binData, { to: 'string' });
      return decompressedData
    }
    if (type == "lz-string") {
      const decompressedData = LZString.decompressFromBase64(base64);
      return decompressedData
    }
  } catch (error) {
    this.addErrorLog(error, "decodeAndDecompress")
    return undefined
  }
}

static atob(str) {
  return DataConverter.atob(str)
}
/**
 * 根据指定的 scheme、host、path、query 和 fragment 生成一个完整的 URL Scheme 字符串。
 * URL Scheme 完整格式：scheme://host/path?query#fragment
 *
 * @param {string} scheme - URL scheme，例如 'myapp'。必须提供。
 * @param {string|undefined} [host] - host 部分，例如 'user_profile'。
 * @param {string|string[]|undefined} [path] - path 部分，例如 'view/123'。
 * @param {Object<string, string|number|boolean|object>|undefined} [query] - 查询参数对象。
 * @param {string|undefined} [fragment] - fragment 标识符，即 URL 中 # 后面的部分。
 * @returns {string} - 生成的完整 URL 字符串。
 */
static generateURLScheme(scheme, host, path, query, fragment) {
  // 1. 处理必须的 scheme
  if (!scheme) {
    console.error("Scheme is a required parameter.");
    return '';
  }
  // 2. 构建基础部分：scheme 和 host
  //    即使 host 为空，也会生成 'scheme://'，这对于 'file:///' 这类 scheme 是正确的
  let url = `${scheme}://${host || ''}`;

  // 3. 添加 path
  if (path) {
    if (Array.isArray(path)) {
      let pathStr = path.join('/')
      url += `/${pathStr.replace(/^\/+/, '')}`;
    }else{
      // 确保 host 和 path 之间只有一个斜杠，并处理 path 开头可能存在的斜杠
      url += `/${path.replace(/^\/+/, '')}`;
    }
  }

  // 4. 添加 query 参数
  if (query && Object.keys(query).length > 0) {
    const queryParts = [];
    for (const key in query) {
      // 确保我们只处理对象自身的属性
      if (Object.prototype.hasOwnProperty.call(query, key)) {
        const value = query[key];
        const encodedKey = encodeURIComponent(key);
        // 对值进行编码，如果是对象，则先序列化为 JSON 字符串
        const encodedValue = encodeURIComponent(
          typeof value === "object" && value !== null ? JSON.stringify(value) : value
        );
        queryParts.push(`${encodedKey}=${encodedValue}`);
      }
    }
    if (queryParts.length > 0) {
      url += `?${queryParts.join('&')}`;
    }
  }

  // 5. 添加 fragment
  if (fragment) {
    // Fragment 部分不应该被编码
    url += `#${fragment}`;
  }

  return url;
}
/**
 * 解析 MarginNote 4 UIStatus URL
 * @param {string} encodedURL - 完整的 marginnote4app URL, 需要先decodeURIComponent
 * @returns {object|string} - 解析后的 JSON 对象或字符串，如果解析失败返回 null
 */
static parseMNUIStatusURL(encodedURL) {
    try {
        let urlString = decodeURIComponent(encodedURL)
        // 1. 提取 Payload
        // URL 格式通常为: marginnote4app://uistatus/<PAYLOAD>
        const scheme = "marginnote4app://uistatus/";
        if (!urlString.startsWith(scheme)) {
            this.addErrorLog("不是有效的 MarginNote 4 uistatus URL", "parseMNUIStatusURL")
            return null;
        }
        
        const payload = urlString.slice(scheme.length);
        const binData = DataConverter.base64ToUint8Array(payload);
        // 3. Gzip 解压
        // 使用 pako.ungzip 进行解压
        const decompressedData = pako.ungzip(binData, { to: 'string' });
        // 4. 尝试解析 JSON
        // MarginNote 的数据通常是 JSON 格式，但也可能是纯文本
        try {
            return JSON.parse(decompressedData);
        } catch (e) {
            // 如果不是 JSON，直接返回字符串
            this.addErrorLog("解压后的数据不是标准 JSON，返回原始字符串", "parseMNUIStatusURL")
            return decompressedData;
        }
    } catch (error) {
      this.addErrorLog(error, "parseMNUIStatusURL")
      return undefined;
    }
}

static async getCurrentUIStatusURL(){
  let command = "UIStatusURL"
  this.executeCommand(command)
  await this.delay(0.1)
  let url = this.clipboardText
  let config = this.parseMNUIStatusURL(url)
  return config
}
/**
 * 将 JSON 对象转换为 MarginNote 4 URL
 * @param {object} jsonObj - 要编码的 JSON 对象
 * @returns {string} - 生成的 URL
 */
static generateMNUIStatusURL(jsonObj) {
    try {
        let base64String = this.compressAndEncode(jsonObj)
        // 4. URL 编码
        // Base64 中可能包含 '/' 和 '+'，虽然 marginnote 似乎能处理部分未编码的字符，
        // 但标准做法是进行 URL 编码，以防止传输错误。
        // 之前的解析例子中 URL 是经过 encodeURIComponent 的。
        const urlSafePayload = encodeURIComponent(base64String);

        // 5. 拼接 URL
        return `marginnote4app://uistatus/${urlSafePayload}`;

    } catch (error) {
      this.addErrorLog(error, "generateMNUIStatusURL")
        return null;
    }
}

/**
 * 将 JSON 对象转换为 MarginNote 4 URL
 * @param {object} jsonObj - 要编码的 JSON 对象
 * @returns {string} - 生成的 URL
 */
static setUIStatusByConfig(jsonObj) {
    try {
        let base64String = this.compressAndEncode(jsonObj)
        // 4. URL 编码
        // Base64 中可能包含 '/' 和 '+'，虽然 marginnote 似乎能处理部分未编码的字符，
        // 但标准做法是进行 URL 编码，以防止传输错误。
        // 之前的解析例子中 URL 是经过 encodeURIComponent 的。
        const urlSafePayload = encodeURIComponent(base64String);
        let url = `marginnote4app://uistatus/${urlSafePayload}`
        this.app.openURL(this.genNSURL(url))
    } catch (error) {
      this.addErrorLog(error, "setUIStatusByConfig")
        return null;
    }
}
/**
 * 将 JSON 对象转换为 MarginNote 4 URL
 * @param {object} jsonObj - 要编码的 JSON 对象
 * @returns {Promise<void>}
 */
static async setUIStatusByConfigAsync(jsonObj) {
    try {
        let base64String = this.compressAndEncode(jsonObj)
        // 4. URL 编码
        // Base64 中可能包含 '/' 和 '+'，虽然 marginnote 似乎能处理部分未编码的字符，
        // 但标准做法是进行 URL 编码，以防止传输错误。
        // 之前的解析例子中 URL 是经过 encodeURIComponent 的。
        const urlSafePayload = encodeURIComponent(base64String);
        let url = `marginnote4app://uistatus/${urlSafePayload}`
        await MNUtil.openURLAsync(url)
    } catch (error) {
      this.addErrorLog(error, "setUIStatusByConfig")
        return null;
    }
}
/*
 * 设置当前笔记的脑图缩放比例，好像得配合offset参数，不然不是视觉中心缩放
 * @param {number} scale - 缩放比例，范围在0.1到10之间
 */
static setMindmapZoonScale(scale){
  let config = {
    topicid: MNUtil.currentNotebookId,
    mapLocation:{
      scale:scale
    }
  }
  this.setUIStatusByConfig(config)
}
static setSideBar(open = true){
  let config = {
    topicid: MNUtil.currentNotebookId,
    sidebar: open
  }
  this.setUIStatusByConfig(config)
}
static searchInSideBar(searchText,type = "name"){
  let config = {
    topicid: MNUtil.currentNotebookId,
    sidebar: true,
    sidesearch: true,
    sideseg:0,
    sidetext: searchText
  }
  if (type == "name") {
    config.sideseg = 0
  }else if (type == "text") {
    config.sideseg = 1
  }
  this.setUIStatusByConfig(config)
}
static _getFloatSearchWebview(){
  // this.log("getFloatSearchWebview")
  let possibleFloatSidebars = MNUtil.studyView.subviews.filter(view=>{
    // return view.frame.y > 20 && view.frame.y < 100 && view.frame.width > 100 && view.frame.height > 100
    return view.frame.y === 60
  })
  // let possibleFloatSidebarsFrames = possibleFloatSidebars.map(view=>{
  //   return view.frame
  // })
  // this.log("possibleFloatSidebars",possibleFloatSidebarsFrames)
  // let frames = MNUtil.studyView.subviews.map(view=>{
  //   return view.frame
  // })
  // this.log("frames",frames)
  // let floatSidebar = MNUtil.studyView.subviews[27]
  if (possibleFloatSidebars.length === 0) {
    return undefined
  }
  let floatSidebar = possibleFloatSidebars[0]
  // this.log("frames:"+floatSidebar.subviews.length)
  let searchView = floatSidebar.subviews[0]
  // let searchViewTab = searchView.subviews[0]
  // let searchViewBottom = searchView.subviews[1]
  let webview = searchView.subviews[2]
  if(webview instanceof UIWebView){
    return webview
  }
  return undefined
}
static _getFixedSearchWebview(){
    // this.log("getFixedSearchWebview")
    let fixedRightSidebar = this.fixedRightSidebar
    if(!fixedRightSidebar){
      return undefined
    }
    let possibleMainViews = fixedRightSidebar.subviews[0].subviews.filter(view=>{
      return (view.frame.height >50) 
    })
    let possibleMainView = possibleMainViews[0]
    if(possibleMainView instanceof UIWebView){
      return possibleMainView
    }
    return undefined
}
static isSearchWebviewShown(){
  let isFixedRightSidebarShown = this.isFixedRightSidebarOpen
  if(isFixedRightSidebarShown){//先判断是否开启了固定右侧边栏
    let webview = this._getFixedSearchWebview()
    if(webview){
      return true
    }
  }else{
    let webview = this._getFloatSearchWebview()
    if(webview){
      return true
    }
  }
  return false
}
static getSearchWebviewURL(){
  let isFixedRightSidebarShown = this.isFixedRightSidebarOpen
  if(isFixedRightSidebarShown){//先判断是否开启了固定右侧边栏
    let webview = this._getFixedSearchWebview()
    if(webview){
      return webview.request.URL().absoluteString()
    }
  }else{
    let webview = this._getFloatSearchWebview()
    if(webview){
      return webview.request.URL().absoluteString()
    }
  }
  return undefined
}
static async getSearchWebview(force = false){
try {

  let isFixedRightSidebarShown = this.isFixedRightSidebarOpen
  if(isFixedRightSidebarShown){//先判断是否开启了固定右侧边栏
    let webview = this._getFixedSearchWebview()
    if(webview){
      return webview
    }
  }else{
    let webview = this._getFloatSearchWebview()
    if(webview){
      return webview
    }
  }
  if (!force) {
    return undefined
  }
  this.showResearchView()
  await this.delay(0.5)
  //需要重新判断，因为研究视图既有可能在固定右侧边栏，也有可能在浮动右侧边栏
  isFixedRightSidebarShown = this.isFixedRightSidebarOpen
  if(isFixedRightSidebarShown){
    let webview = this._getFixedSearchWebview()
    if(webview){
      return webview
    }
  }
  let webview = this._getFloatSearchWebview()
  if(webview){
    return webview
  }
  return undefined
  
} catch (error) {
  this.addErrorLog(error, "getSearchWebview")
  return undefined
}
}
static showResearchView(){
  let config = {
    topicid: MNUtil.currentNotebookId,
    research:1
  }
  this.setUIStatusByConfig(config)
}
static openURLInResearch(url,needEncode = false){
  let config = {
    topicid: MNUtil.currentNotebookId,
    research:1,
    researchurl: needEncode ? encodeURIComponent(url) : url
  }
  this.setUIStatusByConfig(config)
}
static async openURLInResearchAsync(url,needEncode = false){
  let config = {
    topicid: MNUtil.currentNotebookId,
    research:1,
    researchurl: needEncode ? encodeURIComponent(url) : url
  }
  await this.setUIStatusByConfigAsync(config)
}
static openNoteEditor(noteId){
  let config = {
    topicid: MNUtil.currentNotebookId,
    cardedit:1,
    cardid: noteId
  }
  this.setUIStatusByConfig(config)
}

static selectNotesInMindmap(noteIds){
  let config = {
    topicid: MNUtil.currentNotebookId,
    mapsellst: noteIds
  }
  this.setUIStatusByConfig(config)
}
/**
 * 设置当前笔记的主题
 * @param {string} themeName - 主题名称，如 "Default", "aaqqse", "Light"
 */
static setTheme(themeName){
  let config = {
    topicid: MNUtil.currentNotebookId,
    theme: themeName
  }
  this.setUIStatusByConfig(config)
}
/**
 * 获取当前日期
 * @returns {number} - 当前日期
 */
  static getToday() {
    // 创建一个新的Date对象，默认情况下它会包含当前日期和时间
    const today = new Date();
    // 获取日
    const day = today.getDate();
    return day
  }


static async convertImageBase64ToPdfBase64(pngBase64){
  try{
    let pdfBase64 = await PDFTools.convertImageBase64ToPdfBase64(pngBase64)
    return pdfBase64
  }catch(error){
    this.addErrorLog(error, "convertImageBase64ToPdfBase64")
    return undefined
  }
}
static async convertImageDataToPdfData(imageData){
  let imageBase64 = imageData.base64Encoding()
  let pdfBase64 = await this.convertImageBase64ToPdfBase64(imageBase64)
  let pdfData = this.dataFromBase64(pdfBase64,"pdf")
  return pdfData
}



  /**
   * Retrieves the version of the application.
   * 
   * This method checks if the application version has already been set. If not,
   * it sets the version using the `appVersion` method. The version is then
   * returned.
   * 
   * @returns {{version: string,type: string;}} The version of the application.
   */
  static get version(){
    if (!this.mnVersion) {
      this.mnVersion = this.appVersion()
    }
    return this.mnVersion
  }
  static _isTagComment_(comment){
    if (comment.type === "TextNote") {
      if (/^#\S/.test(comment.text)) {
        return true
      }else{
        return false
      }
    }
    return false
  }
  static get app(){
    // this.appInstance = Application.sharedInstance()
    // return this.appInstance
    if (!this.appInstance) {
      this.appInstance = Application.sharedInstance()
    }
    return this.appInstance
  }
  static get db(){
    if (!this.data) {
      this.data = Database.sharedInstance()
    }
    return this.data
  }
  static get currentWindow(){
    //关闭mn4后再打开，得到的focusWindow会变，所以不能只在init做一遍初始化
    return this.app.focusWindow
  }
  static get windowWidth(){
    return this.currentWindow.frame.width
  }
  static get windowHeight(){
    return this.currentWindow.frame.height
  }
  static get studyController(){
    return this.app.studyController(this.currentWindow)
  }
  static get studyView() {
    return this.app.studyController(this.currentWindow).view
  }
  static get studyWidth(){
    return this.studyView.frame.width
  }
  static get studyRight(){
    return this.studyView.frame.x+this.studyView.frame.width
  }
  static get studyHeight(){
    return this.studyView.frame.height
  }
  static get isLeftSidebarOpen(){
    return this.leftSidebarWidth > 0
  }
  static get leftSidebarWidth(){
    return this.studyView.frame.x
  }
  static get isFixedRightSidebarOpen(){
    let isFixedRightSidebarOpen = this.studyRight !== this.windowWidth
    return isFixedRightSidebarOpen
  }
  static get fixedRightSidebarWidth(){
    return this.windowWidth - (this.studyRight)
  }
  static get fixedRightSidebar(){
  try {

    let windowWidth = this.windowWidth
    let studyRight = this.studyRight
    let isFixedRightSidebarOpen = studyRight !== windowWidth
    if (!isFixedRightSidebarOpen) {
      return undefined
    }
    let fixedRightSidebarWidth = windowWidth - studyRight
    let tem = this.currentWindow.subviews[0].subviews[0].subviews[0]
    let possibleRightSidebars = tem.subviews.filter(view=>{
      return (view.frame.x === studyRight) && (view.frame.width === fixedRightSidebarWidth)
    })
    let possibleRightSidebar = possibleRightSidebars.at(-1)
    return possibleRightSidebar
    
  } catch (error) {
    this.addErrorLog(error, "fixedRightSidebar")
    return undefined
  }
  }
  static get isFloatRightSidebarOpen(){
    let possibleFloatSidebars = this.studyView.subviews.filter(view=>{
      // return view.frame.y > 20 && view.frame.y < 100 && view.frame.width > 100 && view.frame.height > 100
      return view.frame.y === 60
    })
    return possibleFloatSidebars.length > 0
  }
  static get floatRightSidebar(){
    let possibleFloatSidebars = this.studyView.subviews.filter(view=>{
      // return view.frame.y > 20 && view.frame.y < 100 && view.frame.width > 100 && view.frame.height > 100
      return view.frame.y === 60
    })
    if (possibleFloatSidebars.length === 0) {
      return undefined
    }
    return possibleFloatSidebars[0]
  }
  static get floatRightSidebarPosition(){
    let possibleFloatSidebars = this.studyView.subviews.filter(view=>{
      // return view.frame.y > 20 && view.frame.y < 100 && view.frame.width > 100 && view.frame.height > 100
      return view.frame.y === 60
    })
    if (possibleFloatSidebars.length === 0) {
      return undefined
    }
    let floatRightSidebar = possibleFloatSidebars[0]
    if (floatRightSidebar.frame.x < 50) {
      return "left"
    }else{
      return "right"
    }
  }
  static get floatRightSidebarWidth(){
    let possibleFloatSidebars = this.studyView.subviews.filter(view=>{
      // return view.frame.y > 20 && view.frame.y < 100 && view.frame.width > 100 && view.frame.height > 100
      return view.frame.y === 60
    })
    if (possibleFloatSidebars.length === 0) {
      return undefined
    }
    let floatRightSidebar = possibleFloatSidebars[0]
    return floatRightSidebar.frame.width
  }
  static get isVertical(){
    return this.studyHeight > this.studyWidth
  }
  static get isHorizontal(){
    return this.studyWidth > this.studyHeight
  }
  static get orientation(){
    return this.isVertical ? "vertical" : "horizontal"
  }
  /**
   * @returns {{view:UIView}}
   **/
  static get extensionPanelController(){
    return this.studyController.extensionPanelController
  }
  /**
   * @returns {UIView}
   */
  static get extensionPanelView(){
    return this.studyController.extensionPanelController.view
  }
  static get extensionPanelOn(){
    if (this.extensionPanelController && this.extensionPanelController.view.window) {
      return true
    }
    return false
  }
  static get mainPath(){
    return this.mainPath
  }
  /**doc:0,1;study:2;review:3 */
  static get studyMode(){
    return this.studyController.studyMode
  }
  static get readerController() {
    return this.studyController.readerController
  }
  static get notebookController(){
    return this.studyController.notebookController
  }
  static get docControllers() {
    return this.studyController.readerController.documentControllers
  }
  static get currentDocController() {
    return this.studyController.readerController.currentDocumentController
  }
  static get mindmapView(){
    return this.studyController.notebookController.mindmapView
  }
  static get selectionText(){
    let selectionText = this.currentDocController.selectionText
    if (selectionText) {
      return selectionText
    }
    if (this.docMapSplitMode) {//不为0则表示documentControllers存在
      let docControllers = this.docControllers
      let docNumber = docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = docControllers[i];
        selectionText = docController.selectionText
        if (selectionText) {
          return selectionText
        }
      }
    }
    if (this.popUpSelectionInfo) {
      let docController = this.popUpSelectionInfo.docController
      if (docController.selectionText) {
        return docController.selectionText
      }
    }
    return undefined
  }
  static get isSelectionText(){
    let image = this.currentDocController.imageFromSelection()
    if (image) {
      return this.currentDocController.isSelectionText
    }
    if (this.docMapSplitMode) {//不为0则表示documentControllers存在
      let docControllers = this.docControllers
      let docNumber = docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = docControllers[i];
        image = docController.imageFromSelection()
        if (image) {
          return docController.isSelectionText
        }
      }
    }
    if (this.popUpSelectionInfo) {
      let docController = this.popUpSelectionInfo.docController
      image = docController.imageFromSelection()
      if (image) {
        return docController.isSelectionText
      }
    }
    return false
  }
  /**
   * 当前激活的文本视图
   * @type {UITextView|undefined}
   */
  static activeTextView = undefined
  static selectionRefreshTime = 0
  /**
   * 返回选中的内容，如果没有选中，则onSelection属性为false
   * 如果有选中内容，则同时包括text和image，并通过isText属性表明当时是选中的文字还是图片
   * Retrieves the current selection details.
   * 
   * This method checks for the current document controller's selection. If an image is found,
   * it generates the selection details using the `genSelection` method. If no image is found
   * in the current document controller, it iterates through all document controllers if the
   * study controller's document map split mode is enabled. If a selection is found in the
   * pop-up selection info, it also generates the selection details. If no selection is found,
   * it returns an object indicating no selection.
   * 
   * @returns {{onSelection: boolean, image: null|undefined|NSData, text: null|undefined|string, isText: null|undefined|boolean,docMd5:string|undefined,pageIndex:number|undefined}} The current selection details.
   */
  static getCurrentSelection(){
    if (this.activeTextView && this.activeTextView.selectedRange.length>0) {
      let range = this.activeTextView.selectedRange
      return {onSelection:true,image:undefined,text:this.activeTextView.text.slice(range.location,range.location+range.length),isText:true,docMd5:undefined,pageIndex:undefined,source:"textview"}
    }
    if (this.studyController.readerController.view.hidden) {
      return {onSelection:false}
    }
    let image = this.currentDocController.imageFromSelection()
    if (image) {
      return this.genSelection(this.currentDocController)
    }
    if (this.docMapSplitMode) {//不为0则表示documentControllers存在
      let docControllers = this.docControllers
      let docNumber = docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = docControllers[i];
        if (docController.imageFromSelection()) {
          return this.genSelection(docController)
        }
      }
    }
    if (this.popUpSelectionInfo && this.popUpSelectionInfo.docController) {
      let docController = this.popUpSelectionInfo.docController
      if (docController.imageFromSelection()) {
        return this.genSelection(docController)
      }
    }
    return {onSelection:false}
  }
  static _currentSelection = {}
  /**
   * 返回选中的内容，如果没有选中，则onSelection属性为false
   * 如果有选中内容，则同时包括text和image，并通过isText属性表明当时是选中的文字还是图片
   * Retrieves the current selection details.
   * 
   * This method checks for the current document controller's selection. If an image is found,
   * it generates the selection details using the `genSelection` method. If no image is found
   * in the current document controller, it iterates through all document controllers if the
   * study controller's document map split mode is enabled. If a selection is found in the
   * pop-up selection info, it also generates the selection details. If no selection is found,
   * it returns an object indicating no selection.
   * 
   * @returns {{onSelection: boolean, image: null|undefined|NSData, text: null|undefined|string, isText: null|undefined|boolean,docMd5:string|undefined,pageIndex:number|undefined}} The current selection details.
   */
  static get currentSelection() {
    if (this.selectionRefreshTime) {
      if (Date.now() - this.selectionRefreshTime > 100) {//超过100ms，重新获取选区信息
        this.selectionRefreshTime = Date.now()
        this._currentSelection = this.getCurrentSelection()
        return this._currentSelection
      }else{
        return this._currentSelection
      }
    }else{
      this.selectionRefreshTime = Date.now()
      this._currentSelection = this.getCurrentSelection()
      return this._currentSelection
    }
  }
  static get currentNotebookId() {
    return this.studyController.notebookController.notebookId
  }
  static get currentNotebook() {
    return this.getNoteBookById(this.currentNotebookId)
  }
  /**
   * Hiden = 0, Doc = 1, MindMap = 2, FlashCard = 3
   * @returns {number}
   */
  static get currentNotebookFlags() {
    return this.currentNotebook.flags
  }
  /**
   * @returns {"Hiden" | "Doc" | "MindMap" | "FlashCard" | "Unknown"}
   */
  static get currentNotebookType() {
    let flags = this.currentNotebook.flags
    switch (flags) {
      case 0:
        return "Hiden"
      case 1:
        return "Doc"
      case 2:
        return "MindMap"
      case 3:
        return "FlashCard"
      default:
        return "Unknown"
    }
  }
  static get currentNotebookController() {
    return this.studyController.notebookController
  }
  static rgbaToHex(rgba, includeAlpha = false, toUpperCase = false) {
      // 确保RGB分量在0-255范围内
      const r = Math.max(0, Math.min(255, Math.round(rgba.r)));
      const g = Math.max(0, Math.min(255, Math.round(rgba.g)));
      const b = Math.max(0, Math.min(255, Math.round(rgba.b)));

      // 确保alpha分量在0-1范围内
      const a = Math.max(0, Math.min(1, rgba.a));

      // 将每个颜色分量转换为两位的十六进制
      const rHex = r.toString(16).padStart(2, '0');
      const gHex = g.toString(16).padStart(2, '0');
      const bHex = b.toString(16).padStart(2, '0');

      let hex;
      if (includeAlpha) {
        // 将alpha分量从0-1转换为0-255，然后转换为两位的十六进制
        const aHex = Math.round(a * 255).toString(16).padStart(2, '0');
        // 组合成8位HEX颜色值
        hex = `#${rHex}${gHex}${bHex}${aHex}`;
      } else {
        // 组合成6位HEX颜色值
        hex = `#${rHex}${gHex}${bHex}`;
      }

      // 根据参数决定是否转换为大写
      return toUpperCase ? hex.toUpperCase() : hex;
  }
  static rgbaArrayToHexArray(rgbaArray, includeAlpha = false, toUpperCase = false) {
    return rgbaArray.map(rgba => this.rgbaToHex(rgba,includeAlpha,toUpperCase));
  }
  static getNotebookExcerptColorById(notebookId){
    let notebook = this.getNoteBookById(notebookId)
    let options = notebook.options
    if (options && "excerptColorTemplate" in options && options.useTopicTool2) {
      let excerptColorTemplate = options.excerptColorTemplate
      let colors = this.rgbaArrayToHexArray(excerptColorTemplate,true)
      return colors
    }
    return this.defaultNoteColors
  }
  static noteColorByNotebookIdAndColorIndex(notebookId,colorIndex){
    let notebook = this.getNoteBookById(notebookId)
    let options = notebook.options
    if (options && "excerptColorTemplate" in options && options.useTopicTool2) {
      let excerptColor = options.excerptColorTemplate[colorIndex]
      let color = this.rgbaToHex(excerptColor,true)
      return color
    }
    return this.defaultNoteColors[colorIndex]
  }
  static get currentNotebookExcerptColor(){
    let options = this.currentNotebook.options
    if (options && "excerptColorTemplate" in options && options.useTopicTool2) {
      let excerptColorTemplate = options.excerptColorTemplate
      let colors = this.rgbaArrayToHexArray(excerptColorTemplate,true)
      return colors
    }else{
      return this.defaultNoteColors
    }
  }
  /**
   * @returns {MbBook}
   */
  static get currentDoc() {
    return this.currentDocController.document
  }
  static get currentDocmd5(){
    try {
      const { docMd5 } = this.currentDocController
      if (docMd5 && docMd5.length === 32) return "00000000"
      else return docMd5
    } catch {
      return undefined
    }
  }
  static get currentDocMd5(){
    try {
      const { docMd5 } = this.currentDocController
      if (docMd5 && docMd5.length === 32) return "00000000"
      else return docMd5
    } catch {
      return undefined
    }
  }
  static get isZH(){
    return NSLocale.preferredLanguages()[0].startsWith("zh")
  }
  /**
   * @returns {"Default" | "Dark" | "Light" | "Gray" | "Green" | "Sepia"}
   */
  static get currentTheme(){
    return this.app.currentTheme
  }
  static get currentThemeColor(){
    return this.themeColor[this.app.currentTheme]
  }
  static _previousClipboardText = ""
  static get clipboardText() {
    let clipboardText = UIPasteboard.generalPasteboard().string
    this._previousClipboardText = clipboardText
    return clipboardText
  }
  static get isClipboardTextChanged() {
    let clipboardText = UIPasteboard.generalPasteboard().string
    let isChanged = clipboardText !== this._previousClipboardText
    return isChanged
  }
  static get clipboardImage() {
    return UIPasteboard.generalPasteboard().image
  }
  static get clipboardImageData() {
    let image = this.clipboardImage
    if (image) {
      return image.pngData()
    }
    return undefined
  }
  static get dbFolder(){
    //结尾不带斜杠
    return this.app.dbPath
  }
  static get cacheFolder(){
    //结尾不带斜杠
    return this.app.cachePath
  }
  static get documentFolder() {
    //结尾不带斜杠
    return this.app.documentPath
  }

  static get tempFolder() {
    //结尾不带斜杠
    return this.app.tempPath
  }
  static get splitLine() {
    let study = this.studyController
    let studyFrame = study.view.bounds
    let readerFrame = study.readerController.view.frame
    let hidden = study.readerController.view.hidden//true代表脑图全屏
    let rightMode = study.rightMapMode
    let fullWindow = readerFrame.width == studyFrame.width
    if (hidden || fullWindow) {
      return undefined
    }
    if (rightMode) {
      let splitLine = readerFrame.x+readerFrame.width
      return splitLine
    }else{
      let splitLine = readerFrame.x
      return splitLine
    }
  }
  static _appVersion = undefined
  /**
   * Retrieves the version and type of the application.
   * 
   * This method determines the version of the application by parsing the appVersion property.
   * It categorizes the version as either "marginnote4" or "marginnote3" based on the parsed version number.
   * Additionally, it identifies the operating system type (iPadOS, iPhoneOS, or macOS) based on the osType property.
   *  
   * @returns {{version: "marginnote4" | "marginnote3", type: "iPadOS" | "iPhoneOS" | "macOS"}} An object containing the application version and operating system type.
   */
  static appVersion() {
    if (this._appVersion) {
      return this._appVersion
    }
    try {
    let info = {}
    let version = parseFloat(this.app.appVersion)
    if (version >= 4) {
      info.version = "marginnote4"
      info.versionNumber = version
    }else{
      info.version = "marginnote3"
      info.versionNumber = version
    }
    switch (this.app.osType) {
      case 0:
        info.type = "iPadOS"
        break;
      case 1:
        info.type = "iPhoneOS"
        break;
      case 2:
        info.type = "macOS"
        break;
      default:
        break;
    }
    this._appVersion = info
    return info
    } catch (error) {
      this.addErrorLog(error, "appVersion")
      return undefined
    }
  }
  static isIOS(){
    return this.appVersion().type == "iPhoneOS"
  }
  static isMacOS(){
    return this.appVersion().type == "macOS"
  }
  static isIPadOS(){
    return this.appVersion().type == "iPadOS"
  }
  static isMN4(){
    return this.appVersion().version == "marginnote4"
  }
  static isMN3(){
    return this.appVersion().version == "marginnote3"
  }
  static getMNUtilVersion(){
    let res = this.readJSON(this.mainPath+"/mnaddon.json")
    return res.version
    // this.copyJSON(res)
  }
  static countWords(str) {
    //对中文而言计算的是字数
    const chinese = Array.from(str)
      .filter(ch => /[\u4e00-\u9fa5]/.test(ch))
      .length
    const english = Array.from(str)
      .map(ch => /[a-zA-Z0-9\s]/.test(ch) ? ch : ' ')
      .join('').split(/\s+/).filter(s => s)
      .length
    return chinese + english
  }
  static removePunctuationOnlyElements(arr) {
    // Regular expression to match strings consisting only of punctuation.
    // This regex includes common Chinese and English punctuation marks.
    // \p{P} matches any kind of punctuation character.
    // \p{S} matches any kind of symbol.
    // We also include specific Chinese punctuation not always covered by \p{P} or \p{S} in all JS environments.
    const punctuationRegex = /^(?:[\p{P}\p{S}¡¿〽〃「」『』【】〝〞〟〰〾〿——‘’“”〝〞‵′＂＃＄％＆＇（）＊＋，－．／：；＜＝＞＠［＼］＾＿｀｛｜｝～￥িপূর্ণ！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～])*$/u;

    return arr.filter(item => !punctuationRegex.test(item.trim()));
  }
  static doSegment(str) {
    if (!this.segmentit) {
      this.segmentit = Segmentit.useDefault(new Segmentit.Segment());
    }
    let words = this.segmentit.doSegment(str,{simple:true}).filter(word=>!/^\s*$/.test(word))
    return words
  }
  /**
   * 
   * @param {string} str 
   * @returns {number}
   */
  static wordCountBySegmentit(str) {
    //对中文而言计算的是词数
    if (!this.segmentit) {
      this.segmentit = Segmentit.useDefault(new Segmentit.Segment());
    }
    let words = this.segmentit.doSegment(str,{simple:true}).filter(word=>!/^\s*$/.test(word))
    //去除标点符号
    let wordsWithoutPunctuation = this.removePunctuationOnlyElements(words)
    // MNUtil.copy(wordsWithoutPunctuation)
    return wordsWithoutPunctuation.length
  }
  /**
   * 
   * @param {string} path 
   * @param {boolean} merge 
   * @returns {MbTopic|undefined}
   */
  static importNotebook(path,merge){
    let res = this.db.importNotebookFromStorePathMerge(path,merge)
    let notebook = res[0]
    return notebook
  }
  static subpathsOfDirectory(path){
    return NSFileManager.defaultManager().subpathsOfDirectoryAtPath(path)
  }
  static contentsOfDirectory(path){
    return NSFileManager.defaultManager().contentsOfDirectoryAtPath(path)
  }
  static allNotebooks(){
    return this.db.allNotebooks()
  }
  static allNotebookIds(){
    return this.db.allNotebooks().map(notebook=>notebook.topicId)
  }
  static allDocumentNotebooks(option = {}){
    let exceptNotebookIds = option.exceptNotebookIds ?? []
    let exceptNotebookNames = option.exceptNotebookNames ?? []
    let documentNotebooks = this.allNotebooks().filter(notebook=>{
      let flags = notebook.flags
      if (flags === 1) {
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
    return documentNotebooks
  }
  static allReviewGroups(option = {}){
    let exceptNotebookIds = option.exceptNotebookIds ?? []
    let exceptNotebookNames = option.exceptNotebookNames ?? []
    let reviewGroups = this.allNotebooks().filter(notebook=>{
      let flags = notebook.flags
      if (flags === 3) {
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
    return reviewGroups
  }
  static allStudySets(option = {}){
  try {
    let exceptNotebookIds = option.exceptNotebookIds ?? []
    let exceptNotebookNames = option.exceptNotebookNames ?? []
    let allNotebooks = this.allNotebooks()
    let studySets = allNotebooks.filter(notebook=>{
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
  /**
   * 
   * @param {string|MNNotebook} studySetId 
   * @returns {MNNote[]}
   */
  static notesInStudySet(studySetId = this.currentNotebookId){
    let allNotes
    if (typeof studySetId === "string") {
      allNotes = this.getNoteBookById(studySetId).notes
    }else{
      allNotes = studySetId.notes
    }
    let filteredNotes = allNotes.filter(note=>!note.docMd5.endsWith("_StudySet"))
    return filteredNotes
  }
  static chatNotesInStudySet(studySetId = MNUtil.currentNotebookId){
    let allNotes
    if (typeof studySetId === "string") {
      allNotes = MNUtil.getNoteBookById(studySetId).notes
    }else{
      allNotes = studySetId.notes
    }
    return allNotes.filter(note=>note.docMd5.endsWith("_StudySet"))
  }
/**
 * 辅助方法：将输入的时间转换为 JS Date 对象
 * @param {string|Date|number} date - 输入的时间数据
 * @returns {Date|null}
 */
static convertDate(date) {
  // 1. 如果是 null 或 undefined，返回 null
  if (!date) return null;
  // 2. 如果已经是 Date 对象，直接返回
  if (date instanceof Date) return date;
  // 3. 如果是字符串或时间戳，尝试转换
  const d = new Date(date);
  // 4. 检查是否转换为了有效时间 (避免 Invalid Date)
  return isNaN(d.getTime()) ? null : d;
}
/**
 * 将 NSFileManager 返回的文件属性对象转换为 Node.js fs.Stats 格式
 * @param {Object} nsAttrs - NSFileManager 获取的文件属性
 * @returns {Object} - 模拟 Node.js fs.Stats 的对象
 */
  static convertNsAttrsToFsStats(nsAttrs) {
  // 处理时间：ISO 字符串 → Date 对象

  // 处理权限：NSFilePosixPermissions（十进制）→ Node.js mode（八进制）
  const mode = nsAttrs.NSFilePosixPermissions ? 
    `0o${nsAttrs.NSFilePosixPermissions.toString(8)}` : null;

  // 构建模拟的 Stats 对象
  const stats = {
    // 核心属性（与 Node.js fs.Stats 对齐）
    dev: nsAttrs.NSFileSystemNumber || 0,       // 设备 ID（对应 NSFileSystemNumber）
    ino: nsAttrs.NSFileSystemFileNumber || 0,   // inode 编号（对应 NSFileSystemFileNumber）
    mode: mode ? parseInt(mode, 8) : 0,         // 权限模式（八进制）
    nlink: nsAttrs.NSFileReferenceCount || 1,   // 硬链接数（对应 NSFileReferenceCount）
    uid: nsAttrs.NSFileOwnerAccountID || 0,     // 用户 ID（对应 NSFileOwnerAccountID）
    gid: nsAttrs.NSFileGroupOwnerAccountID || 0,// 组 ID（对应 NSFileGroupOwnerAccountID）
    rdev: 0,                                    // 特殊设备 ID（NSFileManager 无直接对应，默认 0）
    size: nsAttrs.NSFileSize || 0,              // 文件大小（对应 NSFileSize）
    blksize: 4096,                              // 块大小（NSFileManager 无直接对应，默认 4096）
    blocks: nsAttrs.NSFileSize ? Math.ceil(nsAttrs.NSFileSize / 4096) : 0, // 块数（计算值）
    atimeMs: this.convertDate(nsAttrs.NSFileModificationDate)?.getTime() || 0, // 最后访问时间（NSFileManager 无直接对应，暂用修改时间）
    mtimeMs: this.convertDate(nsAttrs.NSFileModificationDate)?.getTime() || 0, // 最后修改时间（对应 NSFileModificationDate）
    ctimeMs: this.convertDate(nsAttrs.NSFileCreationDate)?.getTime() || 0,     // 状态改变时间（对应 NSFileCreationDate）
    birthtimeMs: this.convertDate(nsAttrs.NSFileCreationDate)?.getTime() || 0, // 创建时间（对应 NSFileCreationDate）

    // 时间对象（Node.js Stats 同时提供 ms 和 Date 对象两种格式）
    atime: this.convertDate(nsAttrs.NSFileModificationDate) || new Date(0),
    mtime: this.convertDate(nsAttrs.NSFileModificationDate) || new Date(0),
    ctime: this.convertDate(nsAttrs.NSFileCreationDate) || new Date(0),
    birthtime: this.convertDate(nsAttrs.NSFileCreationDate) || new Date(0),

    // NSFileManager 特有的属性（保留供参考）
    _nsFileType: nsAttrs.NSFileType,
    _nsFileOwnerAccountName: nsAttrs.NSFileOwnerAccountName,
    _nsFileGroupOwnerAccountName: nsAttrs.NSFileGroupOwnerAccountName,
    _nsFileProtectionKey: nsAttrs.NSFileProtectionKey,
    _nsFileExtendedAttributes: nsAttrs.NSFileExtendedAttributes
  };

  // 添加类型判断方法（模拟 Node.js Stats 的 isFile()/isDirectory() 等）
  stats.isFile = stats._nsFileType === 'NSFileTypeRegular';
  stats.isDirectory = stats._nsFileType === 'NSFileTypeDirectory';
  stats.isSymbolicLink = stats._nsFileType === 'NSFileTypeSymbolicLink';
  stats.isFIFO = stats._nsFileType === 'NSFileTypeFIFO';
  stats.isSocket = stats._nsFileType === 'NSFileTypeSocket';
  stats.isBlockDevice = stats._nsFileType === 'NSFileTypeBlockSpecial';
  stats.isCharacterDevice = stats._nsFileType === 'NSFileTypeCharacterSpecial';

  return stats;
}
/**
 * 获取文件属性
 * @param {string} path 
 * @returns {Object}
 * @property {number} size 文件大小
 * @property {number} atimeMs 最后访问时间
 * @property {number} mtimeMs 最后修改时间
 * @property {number} ctimeMs 状态改变时间
 * @property {number} birthtimeMs 创建时间
 * @property {Date} atime 最后访问时间
 * @property {Date} mtime 最后修改时间
 * @property {Date} ctime 状态改变时间
 * @property {Date} birthtime 创建时间
 * @property {string} path 文件路径
 */
  static getFileAttributes(path){
    let fileManager = NSFileManager.defaultManager()
    let attributes = fileManager.attributesOfItemAtPath(path)
    attributes = this.convertNsAttrsToFsStats(attributes)
    attributes.path = path
    return attributes
  }
  static strCode(str) {  //获取字符串的字节数
    var count = 0;  //初始化字节数递加变量并获取字符串参数的字符个数
    var cn = [8211, 8212, 8216, 8217, 8220, 8221, 8230, 12289, 12290, 12296, 12297, 12298, 12299, 12300, 12301, 12302, 12303, 12304, 12305, 12308, 12309, 65281, 65288, 65289, 65292, 65294, 65306, 65307, 65311]
    var half = [32, 33, 34, 35, 36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 58, 59, 60, 61, 62, 63, 64, 91, 92, 93, 94, 95, 96, 123, 124, 125, 126,105,108,8211]
    if (str) {  //如果存在字符串，则执行
      let len = str.length;
        for (var i = 0; i < len; i++) {  //遍历字符串，枚举每个字符
        let charCode = str.charCodeAt(i)
            if (charCode>=65 && charCode<=90) {
              count += 1.5;  //大写
        } else if (half.includes(charCode)) {
              count +=0.45
        } else if (cn.includes(charCode)) {
              count +=0.8
            }else if (charCode > 255) {  //字符编码大于255，说明是双字节字符(即是中文)
                count += 2;  //则累加2个
            }else{
                count++;  //否则递加一次
            }
        }
        return count;  //返回字节数
    } else {
        return 0;  //如果参数为空，则返回0个
    }
  }
/**
 * 判断字符串是否包含符合特定语法的搜索内容。
 * 支持 .AND., .OR. 和括号 ()。
 *
 * @param {string} text - 要在其中搜索的完整字符串。
 * @param {string} query - 基于 .AND. 和 .OR. 语法的搜索查询字符串。
 * @returns {boolean} - 如果 text 包含符合 query 条件的内容，则返回 true，否则返回 false。
 */
static textMatchPhrase(text, query) {
  // 1. 提取所有独立的搜索关键词。
  // 通过分割 .AND. .OR. 和括号，然后清理，来获取关键词列表。
  const terms = query
    .split(/\s*\.AND\.|\s*\.OR\.|\(|\)/)
    .map(term => term.trim())
    .filter(Boolean); // 过滤掉因分割产生的空字符串

  // 按长度降序排序，以防止在替换时，短关键词（如 "TC"）错误地替换了长关键词（如 "TCG"）的一部分。
  terms.sort((a, b) => b.length - a.length);

  // 辅助函数：用于在最终的表达式中检查单个关键词是否存在（不区分大小写）。
  const check = (term) => text.toLowerCase().includes(term.toLowerCase());

  // 2. 构建一个标准的 JavaScript 布尔表达式字符串。
  let jsQuery = query;

  // 将每个关键词替换为一个函数调用。
  // 例如 "tropical cyclone" -> 'check("tropical cyclone")'
  terms.forEach(term => {
    // 使用正则表达式的全局替换，确保所有出现的地方都被替换。
    // RegExp.escape is not a standard function, so we manually escape special characters.
    const escapedTerm = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    jsQuery = jsQuery.replace(new RegExp(escapedTerm, 'g'), `check("${term}")`);
  });

  // 将自定义的 .AND. 和 .OR. 替换为 JavaScript 的 && 和 ||。
  jsQuery = jsQuery.replace(/\s*\.AND\.\s*/g, ' && ').replace(/\s*\.OR\.\s*/g, ' || ');

  // 3. 使用 new Function() 安全地执行构建好的表达式。
  // 这种方法比 eval() 更安全，因为它在自己的作用域内运行。
  try {
    const evaluator = new Function('check', `return ${jsQuery};`);
    return evaluator(check);
  } catch (error) {
    console.error("查询语法无效:", error);
    return false; // 如果查询语法有误，则返回 false。
  }
}
  static allDocuments(){
    return this.db.allDocuments()
  }
  static allDocumentIds(){
    return this.db.allDocuments().map(document=>document.docMd5)
  }
  static getNoteFileById(noteId) {
    let note = this.getNoteById(noteId)
    let docFile = this.getDocById(note.docMd5)
    if (!docFile) {
      this.showHUD("No file")
      return {
        fileExists:false
      }
    }
    let fullPath
    if (docFile.fullPathFileName) {
      fullPath = docFile.fullPathFileName
    }else{
      let folder = this.documentFolder
      let fullPath = folder+"/"+docFile.pathFile
      if (docFile.pathFile.startsWith("$$$MNDOCLINK$$$")) {
        let fileName = this.getFileName(docFile.pathFile)
        fullPath = Application.sharedInstance().tempPath + fileName
        // fullPath = docFile.pathFile.replace("$$$MNDOCLINK$$$", "/Users/linlifei/")
      }
    }
    if (!this.isfileExists(fullPath)) {
      this.showHUD("Invalid file: "+docFile.pathFile)
      return {
        fileExists:false
      }
    }
    // copy(fullPath)
    let fileName = this.getFileName(fullPath)
    return{
      name:fileName,
      path:fullPath,
      md5:docFile.docMd5,
      fileExists:true,
      pageCount:docFile.pageCount
    }
  }
  static isNSNull(obj){
    return (obj === NSNull.new())
  }
  /**
   * 
   * @param {string} path 
   */
  static createFolder(path){
    this.createFolderDev(path)
  }
  /**
   * 如果中间有文件夹不存在,则会创建对应文件夹
   * @param {string} path 
   */
  static createFolderDev(path){
    if (!this.isfileExists(path)) {
      NSFileManager.defaultManager().createDirectoryAtPathWithIntermediateDirectoriesAttributes(path, true, undefined)
    }
  }
  /**
   * 
   * @param {NSData} data 
   * @param {string} path
   */
  static writeDataToFile(data,path){
  try {
    let folder = this.getFileFolder(path)
    this.createFolderDev(folder)
    data.writeToFileAtomically(path,true)
    return true
  } catch (error) {
    this.addErrorLog(error, "writeDataToFile")
    return false
  }
  }
  /**
   * 
   * @param {string} path 
   * @returns 
   */
  static getFileFold(path){
    return path.split("/").slice(0, -1).join("/")
  }
  /**
   * 
   * @param {string} path 
   * @returns 
   */
  static getFileFolder(path){
    return path.split("/").slice(0, -1).join("/")
  }
  /**
   * 理论上也可以把数据先读到内存中，然后再写到目标文件中，但是这样可能会导致内存占用过高，所以还是直接使用复制API比较好
   * 注意checkMD5选项是需要先把目标文件读到内存中的，对于大文件实际上既耗时又占用内存，所以最好还是不要使用这个选项
   * @param {string} sourcePath 
   * @param {string} targetPath 
   * @param {Object} option 
   * @param {boolean} option.force 是否强制复制，如果为true，则当目标文件存在时，会移动到缓存文件夹
   * @param {boolean} option.checkMD5 是否检查MD5，如果为true，则当目标文件的MD5与源文件的MD5相同时，则直接返回true
   * @param {boolean} option.checkFolder 是否检查文件夹，如果为true，则当目标文件夹不存在时，会创建目标文件夹
   * @returns {boolean}
   */
  static copyFile(sourcePath, targetPath,option = {}){
    try {
      let targetFileExists = this.isfileExists(targetPath)
      let shouldCopy = option.force || option.checkMD5 || !targetFileExists
      let checkFolder = option.checkFolder??true
      if (shouldCopy) {
        if (checkFolder) {
        let folder = this.getFileFold(targetPath)
        if (!this.isfileExists(folder)) {
          this.createFolderDev(folder)
        }
        }
        if (targetFileExists) {
          if (option.checkMD5) {
            let targetMD5 = this.getFileMD5(targetPath)
            let sourceMD5 = this.getFileMD5(sourcePath)
            if (targetMD5 === sourceMD5) {//如果目标文件的MD5与源文件的MD5相同，则直接返回true
              console.log("copyFile skip")
              return true
            }
            this.moveFileToCacheFolder(targetPath)
          }else if (option.force) {
            this.moveFileToCacheFolder(targetPath)
          }
        }
        let success = NSFileManager.defaultManager().copyItemAtPathToPath(sourcePath, targetPath)
        return success
      }
    } catch (error) {
      this.addErrorLog(error, "copyFile")
      return false
    }
  }
  /**
   * 
   * @param {string} sourcePath 
   * @param {string} targetPath 
   * @returns {boolean}
   */
  static moveFile(sourcePath, targetPath){
    try {
      if (!this.isfileExists(targetPath)) {
        let folder = this.getFileFold(targetPath)
        if (!this.isfileExists(folder)) {
          this.createFolderDev(folder)
        }
        let success = NSFileManager.defaultManager().moveItemAtPathToPath(sourcePath, targetPath)
        return success
      }else{
        this.addErrorLog("Target file already exists!", {sourcePath:sourcePath,targetPath:targetPath})
        return false
      }
    } catch (error) {
      this.addErrorLog(error, "moveFile")
      return false
    }
  }
  /**
   * 
   * @param {string} path 
   * @returns {string}
   */
  static moveFileToCacheFolder(path){
    let cacheFolder = this.cacheFolder
    let fileName = this.getFileName(path)
    let ext = fileName.split(".").pop()
    let fileBase = fileName.split(".").slice(0, -1).join(".")
    let newFileName = fileBase+"_"+Date.now()+"."+ext
    let newPath = cacheFolder+"/"+newFileName
    let success = this.moveFile(path, newPath)
    return success
  }
  /**
   * 
   * @param {string} path 
   * @returns {string}
   */
  static moveFolderToCacheFolder(path){
    //如果文件夹不存在,则直接返回true
    if (!this.isfileExists(path)) {
      return true
    }
    let cacheFolder = this.cacheFolder
    let folderName = this.getFileName(path)
    let newFolderName = folderName+"_"+Date.now()
    let newPath = cacheFolder+"/"+newFolderName
    let success = this.moveFile(path, newPath)
    // if (success) {
    //   this.log("✅ moveFolderToCacheFolder",path)
    // }
    return success
  }
  static moveToCacheFolder(path){

    let stats = this.getFileAttributes(path)
    if (stats.isDirectory) {
      return this.moveFolderToCacheFolder(path)
    }else{
      return this.moveFileToCacheFolder(path)
    }
  }
  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} script 
   * @returns 
   */
  static async runJavaScript(webview,script) {
    // if(!this.webviewResponse || !this.webviewResponse.window)return;
    return new Promise((resolve, reject) => {
      try {
        if (webview) {
          // MNUtil.copy(webview)
          webview.evaluateJavaScript(script,(result) => {
            if (this.isNSNull(result)) {
              resolve(undefined)
            }
            resolve(result)
          });
        }else{
          resolve(undefined)
        }
      } catch (error) {
        this.addErrorLog(error, "runJavaScript")
        resolve(undefined)
      }
    })
  };

static async webviewBlur(webView){
    await this.runJavaScript(webView,`function removeFocus() {
    // 获取当前具有焦点的元素
    const focusedElement = document.activeElement;
    // 如果当前焦点元素存在，移除焦点
    if (focusedElement) {
        focusedElement.blur();
    }
}
removeFocus()`)
    webView.endEditing(true)
}
  static getRandomElement(arr) {
    if (arr.length === 1) {
      return arr[0]
    }
    if (arr && arr.length) {
      const randomIndex = Math.floor(Math.random() * arr.length);
      return arr[randomIndex];
    }
    return ""; // 或者抛出一个错误，如果数组为空或者未定义
  }
  /**
   * Displays a Heads-Up Display (HUD) message on the specified window for a given duration.
   * 
   * This method shows a HUD message on the specified window for the specified duration.
   * If no window is provided, it defaults to the current window. The duration is set to 2 seconds by default.
   * 
   * @param {string} message - The message to display in the HUD.
   * @param {number} [duration=2] - The duration in seconds for which the HUD should be displayed.
   * @param {UIWindow} [window=this.currentWindow] - The window on which the HUD should be displayed.
   */
  static showHUD(message, duration = 2, view = this.currentWindow) {
    // if (this.onWaitHUD) {
    //   this.stopHUD(view)
    // }
    this.app.showHUD(message, view, duration);
  }
  static waitHUD(message, view = this.currentWindow) {
    // if (this.onWaitHUD) {
    //   return
    // }
    this.app.waitHUDOnView(message, view);
    this.onWaitHUD = true
  }
  static async stopHUD(delay = 0, view = this.currentWindow) {
    if (typeof delay === "number") {
      await MNUtil.delay(delay)
    }
    this.app.stopWaitHUDOnView(view);
    this.onWaitHUD = false
  }

  // static cancelString = Locale.getLocalNameForKey("cancel")
  // static confirmString = Locale.getLocalNameForKey("confirm")
  static get cancelString(){
    return Locale.cancelString
  }
  static get confirmString(){
    return Locale.confirmString
  }
   /**
   * Displays a confirmation dialog with a main title and a subtitle.
   * 
   * This method shows a confirmation dialog with the specified main title and subtitle.
   * It returns a promise that resolves with the button index of the button clicked by the user.
   * 
   * @param {string} mainTitle - The main title of the confirmation dialog.
   * @param {string|object} subTitle - The subtitle of the confirmation dialog.
   * @returns {Promise<number|undefined>} A promise that resolves with the button index of the button clicked by the user.
   */
  static async alert(mainTitle,subTitle=""){
    if (MNOnAlert) {
      return
    }
    let typeofSubTitle = typeof subTitle
    let fixedSubtitle = typeofSubTitle === "string"?subTitle:JSON.stringify(subTitle,undefined,2)
    MNOnAlert = true
    return new Promise((resolve, reject) => {
      UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
        mainTitle,fixedSubtitle,0,this.confirmString,[],
        (alert, buttonIndex) => {
          MNOnAlert = false
          // MNUtil.copyJSON({alert:alert,buttonIndex:buttonIndex})
          resolve(buttonIndex)
        }
      )
    })
  }
   /**
   * Displays a confirmation dialog with a main title and a subtitle.
   * 
   * This method shows a confirmation dialog with the specified main title and subtitle.
   * It returns a promise that resolves with the button index of the button clicked by the user.
   * 
   * @param {string} mainTitle - The main title of the confirmation dialog.
   * @param {string|object} subTitle - The subtitle of the confirmation dialog.
   * @param {string[]} items - The items of the confirmation dialog.只有两个按钮,第一个是取消,第二个是确认
   * @returns {Promise<boolean>} A promise that resolves with the button index of the button clicked by the user.
   */
  static async confirm(mainTitle,subTitle="",items = [this.cancelString,this.confirmString]){
  try {
    if (MNOnAlert) {
      return false
    }
    let typeofSubTitle = typeof subTitle
    let fixedSubtitle = typeofSubTitle === "string"?subTitle:JSON.stringify(subTitle,undefined,2)
    MNOnAlert = true
    return new Promise((resolve, reject) => {
      UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
        mainTitle,fixedSubtitle,0,items[0],items.slice(1),
        (alert, buttonIndex) => {
          MNOnAlert = false
          // MNUtil.copyJSON({alert:alert,buttonIndex:buttonIndex})
          resolve(buttonIndex === 1)
        }
      )
    })
  } catch (error) {
    MNOnAlert = false
    this.addErrorLog(error, "confirm")
    return false
  }
  }
  /**
   * 0代表用户取消,其他数字代表用户选择的按钮索引
   * @param {string} mainTitle - The main title of the confirmation dialog.
   * @param {string} subTitle - The subtitle of the confirmation dialog.
   * @param {string[]} items - The items to display in the dialog.
   * @returns {Promise<number>} A promise that resolves with the button index of the button clicked by the user.
   */
  static async userSelect(mainTitle,subTitle="",items){
    if (MNOnAlert) {
      return
    }
    MNOnAlert = true
    return new Promise((resolve, reject) => {
      UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
        mainTitle,subTitle,0,this.cancelString,items,
        (alert, buttonIndex) => {
          // MNUtil.copyJSON({alert:alert,buttonIndex:buttonIndex})
          MNOnAlert = false
          resolve(buttonIndex)
        }
      )
    })
  }
  static findToc(md5,excludeNotebookId=undefined){
    let allNotebooks = this.allStudySets({exceptNotebookIds:[excludeNotebookId]}).filter(notebook=>{
      if (notebook.options && "bookGroupNotes" in notebook.options && notebook.options.bookGroupNotes[md5]) {
        let target = notebook.options.bookGroupNotes[md5]
        if ("tocNoteIds" in target) {
          return true
        }
      }
      return false
    })
    if (allNotebooks.length) {
      let targetNotebook = allNotebooks[0]
      let target = targetNotebook.options.bookGroupNotes[md5].tocNoteIds
      let tocNotes = target.map(noteId=>{
        return MNNote.new(noteId)
      })
      return tocNotes
    }else{
      return undefined
    }
  }
  /**
   * 
   * @param {string} md5 
   * @param {string} notebookId 
   * @returns {MNNote[]}
   */
  static getDocTocNotes(md5=this.currentDocmd5,notebookId=this.currentNotebookId){
    let notebook = this.getNoteBookById(notebookId)
    if (notebook.options && "bookGroupNotes" in notebook.options && notebook.options.bookGroupNotes[md5] && "tocNoteIds" in notebook.options.bookGroupNotes[md5]) {
      let target = notebook.options.bookGroupNotes[md5]
      let tocNotes = target.tocNoteIds.map(noteId=>{
        return MNNote.new(noteId)
      })
      // tocNotes[0].focusInDocument()
      return tocNotes
    }else{//在其他笔记本中查找
      return this.findToc(md5,notebookId)
    }

  }
/**
 * 
 * @param {string} content,必须是data url
 * @returns 
 */
static fileTypeFromBase64URL(content) {
  try{
  let tem = content.split(",")
  let prefix = tem[0]
  if (prefix.includes("octet-stream")) {//需要进一步判断
    //通过base64前几个字符判断
    let type = this.getFileTypeFromBase64(content)
    return type
  }
  if (prefix.includes("application/pdf")) {
    return "pdf"
  }
  if (prefix.includes("html")) {
    return "html"
  }
  if (prefix.includes("image/png")) {
    return "png"
  }
  if (prefix.includes("image/jpeg")) {
    return "jpg"
  }
  if (prefix.includes("markdown")){
    return "markdown"
  }
  if (prefix.includes("zip")){
    return "zip"
  }
  }catch(error){
    this.addErrorLog(error, "fileTypeFromBase64")
    return 'unknown';
  }
}

static getFileTypeFromhexHeader(hexHeader) {
  try {
      const fileTypes = {
      'FFD8FF': 'jpg',          // JPG/JPEG
      '89504E47': 'png',        // PNG
      '47494638': 'gif',        // GIF
      '25504446': 'pdf',        // PDF
      '504B0304': 'zip',        // ZIP（包括 docx、xlsx 等）
      '7B5C727466': 'rtf',      // RTF
      '4D5A': 'exe',            // EXE/DLL
      '494433': 'mp3',          // MP3
      '0000001466747970': 'mp4',// MP4
    };

    // 从长前缀到短前缀匹配（避免误判）
    const sortedTypes = Object.entries(fileTypes).sort(([a], [b]) => b.length - a.length);
    for (const [hexPrefix, type] of sortedTypes) {
      if (hexHeader.startsWith(hexPrefix)) {
        return type;
      }
    }
    return 'unknown';
  } catch (error) {
    this.addErrorLog(error, "getFileTypeFromhexHeader")
    return 'unknown';
  }
}
/**
 * 
 * @param {NSData} data 
 * @returns {string} 文件头十六进制字符串
 */
static hexHeaderFromData(data) {
  try {
    let subData = data.subdataWithRange({location:0,length:16})
    let base64 = subData.base64Encoding()
    const uint8Array = DataConverter.base64ToUint8Array(base64)
    const fileHeaderBytes = uint8Array.slice(0, 16); // 取前 16 字节文件头
    const hexHeader = Array.from(fileHeaderBytes)
      .map(byte => byte.toString(16).padStart(2, '0').toUpperCase())
      .join('');
    return hexHeader
  } catch (error) {
    this.addErrorLog(error, "hexHeaderFromData")
    return undefined
  }
}
/**
 * 直接从 Base64 格式的 Data URL 判断文件格式，仅用于不能直接判断base64类型的情况
 * @param {string} base64 - Base64 Data URL（如 data:application/octet-stream;base64,...）
 * @returns {string} 文件格式（如 'jpg', 'png', 'pdf' 等，未知则返回 'unknown'）
 */
static getFileTypeFromBase64(base64) {
  try {
    let data = this.dataFromBase64(base64)
    let hexHeader = this.hexHeaderFromData(data)
    let fileType = this.getFileTypeFromhexHeader(hexHeader)
    return fileType
  } catch (error) {
    this.addErrorLog(error, "getFileTypeFromBase64")
    return 'unknown';
  }
}
/**
 * 
 * @param {NSData|string} data 
 */
static getFileType(data){
  if (data instanceof NSData) {
    return this.getFileTypeFromData(data)
  }
  if (typeof data === "string") {
    if (data.startsWith("data:")) {
      return this.fileTypeFromBase64URL(data)
    }else{
      //单纯的base64字符串，无法直接判断格式
      return this.getFileTypeFromBase64(data)
    }
  }
  return 'unknown'
}
  static copyObject(object) {
        if (object instanceof MNButton) {
          let buttonInfo = {
            type:"MNButton",
            frame:object.frame,
            hasTitle:false,
            subviews:object.subviews.map(subview=>{
              return subview.frame
            })
          }
          if (object.title) {
            buttonInfo.title = object.title
            buttonInfo.titleColor = object.titleColorString
            buttonInfo.hasTitle = true
          }
          buttonInfo.radius = object.radius
          buttonInfo.color = object.colorString
          this.copyJSON(buttonInfo)
          return
        }
        if (object instanceof NSData) {//假设为图片的data
          let fileType = DataConverter.getFileTypeFromData(object)
          switch (fileType) {
            case "jpg":
            case "png":
              this.copyImage(object)
              break;
            case "unknown":
              this.copy("Unknown file type")
              break;
            default:
              this.copy(fileType)
              break;
          }
          return
        }
        if (object instanceof UIImage) {
          this.copyImage(object.pngData())
          return
        }
        if (object instanceof MNDocument) {
          let docInfo = {
            id:object.docMd5,
            currentNotebookId:object.currentTopicId,
            title:object.docTitle,
            pageCount:object.pageCount,
            path:object.fullPathFileName
          }
          this.copyJSON(docInfo)
          return
        }
        if (object instanceof MNNotebook) {
          let notebookInfo = {
            id:object.id,
            title:object.title,
            type:object.type,
            url:object.url,
            mainDocMd5:object.mainDocMd5
          }
          this.copyJSON(notebookInfo)
          return
        }
        // if (object instanceof MbBookNote) {
        //   let noteInfo = {
        //     noteId:object.noteId,
        //     noteTitle:object.noteTitle,
        //     excerptText:object.excerptText,
        //     docMd5:object.docMd5,
        //     notebookId:object.notebookId,
        //     comments:object.comments
        //   }
        //   this.copy(noteInfo)
        //   break;
        // }
        if (object instanceof MNNote) {
          let noteInfo = {
            noteId:object.noteId,
            title:object.title,
            excerptText:object.excerptText,
            docMd5:object.docMd5,
            notebookId:object.notebookId,
            noteURL:object.noteURL,
            MNComments:object.MNComments
          }
          if (object.tags && object.tags.length > 0) {
            noteInfo.tags = object.tags
          }
          this.copyJSON(noteInfo)
          return
        }
        if (object instanceof UIView) {
          let viewInfo = {
            type:"UIView",
            frame:object.frame,
            color:"#"+object.backgroundColor.hexStringValue,
            subviews:object.subviews.map(subview=>{
              return subview.frame
            })
          }
          if (object instanceof UIButton) {
            viewInfo.type = "UIButton"
            let title = object.titleLabel.text
            if (title) {
              viewInfo.title = title
              viewInfo.titleColor = object.titleLabel.textColor.hexStringValue
              viewInfo.hasTitle = true
            }else{
              viewInfo.hasTitle = false
            }
            viewInfo.color = object.colorString
            this.copyJSON(viewInfo)
            return
          }
          if (object instanceof UIWebView) {
            viewInfo.type = "UIWebView"
            viewInfo.requestURL = object.request.URL().absoluteString()
            this.copyJSON(viewInfo)
          }
          this.copyJSON(viewInfo)
          return
        }
        if (object instanceof Error) {
          this.copyJSON({type:"Error",message:object.message})
          return
        }
        this.copyJSON(object)
        return
  }
  /**
   * 自动检测类型并复制
   * @param {string|object|NSData|UIImage} object 
   */
  static copy(object) {
    switch (typeof object) {
      case "string":
        UIPasteboard.generalPasteboard().string = object
        break;
      case "undefined":
        this.showHUD("Undefined")
        break;
      case "number":
        UIPasteboard.generalPasteboard().string = object.toString()
        break;
      case "boolean":
        UIPasteboard.generalPasteboard().string = object.toString()
        break;
      case "object":
        this.copyObject(object)
        break;
      default:
        this.showHUD("Unsupported type: "+typeof object)
        break;
    }
  }
  /**
   * Copies a JSON object to the clipboard as a formatted string.
   * 
   * This method converts the provided JSON object into a formatted string using `JSON.stringify`
   * with indentation for readability, and then sets this string to the clipboard.
   * 
   * @param {Object} object - The JSON object to be copied to the clipboard.
   */
  static copyJSON(object) {
    UIPasteboard.generalPasteboard().string = JSON.stringify(object,null,2)
  }
  /**
   * Copies an image to the clipboard.
   * 
   * This method sets the provided image data to the clipboard with the specified pasteboard type.
   * 
   * @param {NSData} imageData - The image data to be copied to the clipboard.
   */
  static copyImage(imageData) {
    UIPasteboard.generalPasteboard().setDataForPasteboardType(imageData,"public.png")
  }
  /**
   * 
   * @param {string} url
   */
  static openMarginNoteURL(url){
      if (MNUtil.isMN4() && url.startsWith("marginnote3app://")) {
        url = url.replace("marginnote3app://", "marginnote4app://")
      }else if (MNUtil.isMN3() && url.startsWith("marginnote4app://")) {
        url = url.replace("marginnote4app://", "marginnote3app://")
      }
      let config = this.parseURL(url)
      switch (config.host) {//专门处理book和page链接
        case "tocNote":
          let targetNote = MNNote.new(config.pathComponents[0])
          targetNote.focusInDocument()
          return;
        case "book":
        case "page":
          if (config.pathComponents.length < 2){
            this.showHUD("Invalid URL")
            return
          }
          let targetDoc = MNDocument.new(config.pathComponents[0])
          if (config.host === "page") {
            let pageNo = parseInt(config.pathComponents[1].replace("p",""))
            targetDoc.openAtPage(pageNo)
          }else{
            targetDoc.open()
          }
          return
        default:
          break;
      }
      this.app.openURL(NSURL.URLWithString(url))
  }
  /**
   * 
   * @param {string} url
   */
  static async openMarginNoteURLAsync(url){
      if (MNUtil.isMN4() && url.startsWith("marginnote3app://")) {
        url = url.replace("marginnote3app://", "marginnote4app://")
      }else if (MNUtil.isMN3() && url.startsWith("marginnote4app://")) {
        url = url.replace("marginnote4app://", "marginnote3app://")
      }
      let config = this.parseURL(url)
      switch (config.host) {//专门处理book和page链接
        case "tocNote":
          let targetNote = MNNote.new(config.pathComponents[0])
          targetNote.focusInDocument()
          return;
        case "book":
        case "page":
          if (config.pathComponents.length < 2){
            this.showHUD("Invalid URL")
            return
          }
          let targetDoc = MNDocument.new(config.pathComponents[0])
          if (config.host === "page") {
            let pageNo = parseInt(config.pathComponents[1].replace("p",""))
            targetDoc.openAtPage(pageNo)
          }else{
            targetDoc.open()
          }
          return
        default:
          break;
      }
      await this.openURLOptionsCompletionHandler(url);
  }
  /**
   * 当url为marginnote链接时，mode无效
   * @param {string|NSURL} url
   * @param {"auto"|"external"|"mnbrowser"} mode 
   */
  static openURL(url,mode = "external"){
  try {

    let type = this.typeOf(url)

    if (type === "NSURL") {
      let urlString = url.absoluteString()
      if (urlString.startsWith("marginnote")) {
        this.openMarginNoteURL(urlString)
        return
      }
      switch (mode) {
        case "auto":
          if (urlString.startsWith("http://") || urlString.startsWith("https://")) {
            if (typeof browserUtils !== "undefined") {
              MNUtil.postNotification("openInBrowser", {url:urlString})
              break;
            }
          }
          this.app.openURL(url);
          break;
        case "external":
          this.app.openURL(url);
          break;
        case "mnbrowser":
          if (typeof browserUtils !== "undefined") {
            MNUtil.postNotification("openInBrowser", {url:urlString})
          }else{
            MNUtil.showHUD("❌ MN Browser not installed")
          }
          break;
        default:
          break;
      }
      return
    }
    if (typeof url === "string") {
      if (url.startsWith("marginnote")) {
        this.openMarginNoteURL(url)
        return
      }
      switch (mode) {
        case "auto":
          if (url.startsWith("http://") || url.startsWith("https://")) {
            if (typeof browserUtils !== "undefined") {
              MNUtil.postNotification("openInBrowser", {url:url})
              break;
            }
          }
          this.app.openURL(NSURL.URLWithString(url));
          break;
        case "external":
          this.app.openURL(NSURL.URLWithString(url));
          break;
        case "mnbrowser":
          if (typeof browserUtils !== "undefined") {
            MNUtil.postNotification("openInBrowser", {url:url})
          }else{
            MNUtil.showHUD("❌ MN Browser not installed")
          }
          break;
        default:
          break;
      }
      return
    }
  } catch (error) {
    this.addErrorLog(error, "openURL", {url:url,mode:mode})
  }
  }
  /**
   * 当url为marginnote链接时，mode无效
   * @param {string|NSURL} url
   * @param {"auto"|"external"|"mnbrowser"} mode 
   */
  static async openURLAsync(url,mode = "external"){
  try {
    let type = this.typeOf(url)
    if (typeof url === "string") {
      if (url.startsWith("marginnote")) {
        this.openMarginNoteURL(url)
        return
      }
      switch (mode) {
        case "auto":
          if (url.startsWith("http://") || url.startsWith("https://")) {
            if (typeof browserUtils !== "undefined") {
              MNUtil.postNotification("openInBrowser", {url:url})
              break;
            }
          }
          await this.openURLOptionsCompletionHandler(url);
          break;
        case "external":
          await this.openURLOptionsCompletionHandler(url);
          break;
        case "mnbrowser":
          if (typeof browserUtils !== "undefined") {
            MNUtil.postNotification("openInBrowser", {url:url})
          }else{
            MNUtil.showHUD("❌ MN Browser not installed")
          }
          break;
        default:
          break;
      }
      return
    }
    if (type === "NSURL") {
      let urlString = url.absoluteString()
      if (urlString.startsWith("marginnote")) {
        this.openMarginNoteURL(urlString)
        return
      }
      switch (mode) {
        case "auto":
          if (urlString.startsWith("http://") || urlString.startsWith("https://")) {
            if (typeof browserUtils !== "undefined") {
              MNUtil.postNotification("openInBrowser", {url:urlString})
              break;
            }
          }
          await this.openURLOptionsCompletionHandler(url);
          break;
        case "external":
          await this.openURLOptionsCompletionHandler(url);
          break;
        case "mnbrowser":
          if (typeof browserUtils !== "undefined") {
            MNUtil.postNotification("openInBrowser", {url:urlString})
          }else{
            MNUtil.showHUD("❌ MN Browser not installed")
          }
          break;
        default:
          break;
      }
      return
    }

  } catch (error) {
    this.addErrorLog(error, "openURL", {url:url,mode:mode})
  }
  }
  static canOpenURL(url){
    return UIApplication.sharedApplication().canOpenURL(this.genNSURL(url))
  }
  /**
   * 
   * @param {string} url
   * @returns {Promise<boolean>}
   */
  static async openURLOptionsCompletionHandler(url){
  return new Promise((resolve,reject)=>{
  UIApplication.sharedApplication().openURLOptionsCompletionHandler(this.genNSURL(url), {}, (success)=>{
    resolve(success)
  })
  })
  }
static parseTagsToTree(tags) {
  try {
    const tree = [];
    const separator = "/";

    if (!Array.isArray(tags)) return [];

    tags.forEach(tag => {
      const parts = tag.split(separator).map(s => s.trim()).filter(s => s); // 分割并去除空字符
      
      let currentLevel = tree; // 指针，指向当前层级的数组

      parts.forEach((part, index) => {
        // 在当前层级查找是否已经存在该节点
        let existingNode = currentLevel.find(node => node.name === part);

        if (!existingNode) {
          // 如果不存在，创建新节点
          const newNode = {
            name: part,
            path: parts.slice(0, index + 1).join(separator), // 记录完整路径方便后续使用
            children: []
          };
          
          // 如果是路径的最后一个部分（叶子节点），可以加个标记
          if (index === parts.length - 1) {
            newNode.isLeaf = true; 
          }

          currentLevel.push(newNode);
          existingNode = newNode;
        }

        // 指针下移：将当前层级指向该节点的 children，以便处理下一级
        currentLevel = existingNode.children;
      });
    });

    return tree;

  } catch (error) {
    console.error("parseTagsToTree error:", error);
    return [];
  }
}
  static openWith(config,addon = "external"){
    if (addon) {
      let mode
      switch (addon) {
        case "external":
          if ("url" in config) {
            this.openURL(config.url)
          }
          break;
        case "mnbrowser":
          mode = config.mode ?? "openURL"
          switch (mode) {
            case "openURL":
              MNUtil.postNotification("openInBrowser", {url:config.url})
              break;
            case "search":
              let userInfo = {}
              if ("textToSearch" in config) {
                userInfo.text = config.textToSearch
              }
              if ("noteId" in config) {
                userInfo.noteid = config.noteId
              }
              if ("engine" in config) {
                userInfo.engine = config.engine
              }
              MNUtil.postNotification("searchInBrowser", userInfo)
              break;
            default:
              MNUtil.showHUD("mode not found")
              break;
          }
          break;
      
        default:
          break;
      }
    }else{
      MNUtil.showHUD("addon not found")
    }

    
  }
  static compressImage(imageData,quality = 0.1){
    let compressedData
    switch (typeof imageData) {
      case "string":
        if (imageData.startsWith("data:image/jpeg;base64,") || imageData.startsWith("data:image/png;base64,")) {
          let data = this.dataFromBase64(imageData)
          compressedData = UIImage.imageWithData(data).jpegData(quality)
          return compressedData;
        }else{
          let data = this.dataFromBase64(base64,"png")
          compressedData = UIImage.imageWithData(data).jpegData(quality)
          return compressedData;
        }
        break;
      case "NSData":
        compressedData = UIImage.imageWithData(imageData).jpegData(quality)
        return compressedData;
      case "UIImage":
        compressedData = imageData.jpegData(quality)
        return compressedData;
        break;
      default:
        break;
    }
    return undefined
  }
  /**
   * 
   * @param {string} urlString 
   * @returns {{url:string,scheme:string,host:string,query:string,params:Object,pathComponents:string[],isBlank:boolean,fragment:string}}
   */
  static parseURL(urlString){
    /**
     * @type {NSURL}
     */
    let url
    if (typeof urlString === "string") {
      url = NSURL.URLWithString(urlString)
    }else{
      if (urlString instanceof NSURL) {
        url = urlString
      }else if (urlString instanceof NSURLRequest) {
        url = urlString.URL()
      }
    }
    let absoluteString = url.absoluteString()
    if (absoluteString === "about:blank") {
      return {
        url:absoluteString,
        scheme:"about",
        params:{},
        isBlank:true
      }
    }
    let config = {
      url:url.absoluteString(),
      scheme:url.scheme,
      host:url.host,
      query:url.query,
      isBlank:false
    }
    let pathComponents = url.pathComponents()
    if (pathComponents && pathComponents.length > 0) {
      config.pathComponents = pathComponents.filter(k=>k !== "/")
    }

    let fragment = url.fragment
    if (fragment) {
      config.fragment = fragment
    }
    if (url.port) {
      config.port = url.port
    }
    // 解析查询字符串
    const params = {};
    let queryString = url.query;
    if (queryString) {
      const pairs = queryString.split('&');
      for (const pair of pairs) {
        // 跳过空的参数对 (例如 'a=1&&b=2' 中的第二个 '&')
        if (!pair) continue;
        const eqIndex = pair.indexOf('=');
        let key, value;

        if (eqIndex === -1) {
          // 处理没有值的参数，例如 '...&readonly&...'
          key = decodeURIComponent(pair);
          value = ''; // 通常将无值的 key 对应的值设为空字符串
        } else {
          key = decodeURIComponent(pair.substring(0, eqIndex));
          let tem = decodeURIComponent(pair.substring(eqIndex + 1));
          if (MNUtil.isValidJSON(tem)) {
            value = JSON.parse(tem)
          }else if (tem === "true") {
            value = true
          }else if (tem === "false") {
            value = false
          }else{
            value = tem
          }
        }
        params[key] = value;
      }
    }
    config.params = params
    return config
  }
  /**
   * 
   * @param {string|MNNotebook|MbTopic} notebook 
   * @param {boolean} needConfirm 
   */
  static async openNotebook(notebook, needConfirm = false){
    let targetNotebook = MNNotebook.new(notebook)
    if (!targetNotebook) {
      this.showHUD("No notebook")
      return
    }
    if (targetNotebook.id == this.currentNotebookId) {
      MNUtil.refreshAfterDBChanged()
      // this.showHUD("Already in current notebook")
      return
    }
    if (needConfirm) {
      let confirm = await MNUtil.confirm("是否打开学习集？", targetNotebook.title)
      MNUtil.refreshAfterDBChanged()
      if (confirm) {
        MNUtil.openURL("marginnote4app://notebook/"+targetNotebook.id)
      }
    }else{
      MNUtil.openURL("marginnote4app://notebook/"+targetNotebook.id)
    }
  }
  /**
   * 
   * @param {string} noteId 
   * @returns {boolean}
   */
  static isNoteInReview(noteId){
    return this.studyController.isNoteInReview(noteId)
  }
  /**
   * 当删除学习集后,还有可能学习集本身存在,但是对应的笔记清空的情况
   * @param {*} notebookId 
   * @param {*} checkNotes 
   * @returns 
   */
  static notebookExists(notebookId,checkNotes = false){
    let notebook = this.db.getNotebookById(notebookId)
    if (notebook) {
      if (checkNotes) {
        if (notebook.notes && notebook.notes.length > 0) {
          return true
        }
        return false
      }
      return true
    }
    return false
  }
  /**
   * 
   * @param {string|MNNote} noteId 
   * @returns {boolean}
   */
  static noteExists(noteId){
    if (noteId instanceof MNNote) {
      return noteId.exist()
    }
    if (noteId && noteId.trim()){
      let note = this.db.getNoteById(noteId)
      if (note) {
        return true
      }
    }
    return false
  }
  /**
   * 
   * @param {string} noteid 
   * @returns {MbBookNote}
   */
  static getNoteById(noteid,alert = true) {
    let note = this.db.getNoteById(noteid)
    if (note) {
      return note
    }else{
      if (alert){
        this.log({
          level:'error',
          message:'Note not exist!',
          detail:noteid
        })
      }
      return undefined
    }
  }
  static getNoteBookById(notebookId) {
    let notebook = this.db.getNotebookById(notebookId)
    return notebook
  }
  // static cachedDocs = {}
  static getDocById(md5) {
    // if (this.cachedDocs[md5]) {
    //   return this.cachedDocs[md5]
    // }
    let doc = this.db.getDocumentById(md5)
    // if (doc) {
    //   this.cachedDocs[md5] = doc
    // }
    return doc
  }
  /**
   *
   * @param {String} url
   * @returns {String}
   */
  static getNoteIdByURL(url) {
    let config = this.parseURL(url.trim())
    let targetNoteId = config.pathComponents[0]
    return targetNoteId
  }
  static getNoteURLById(noteId){
    if (this.isMN3()) {
      return "marginnote3app://note/"+noteId
    }else{
      return "marginnote4app://note/"+noteId
    }
  }
  /**
   *
   * @param {String} url
   * @returns {String}
   */
  static getNotebookIdByURL(url) {
    let targetNotebookId = url.trim()
    if (/^marginnote\dapp:\/\/notebook\//.test(targetNotebookId)) {
      targetNotebookId = targetNotebookId.slice(22)
    }
    return targetNotebookId
  }
  /**
   * 
   * @param {string}filePath The file path of the document to import
   * @returns {string} The imported document md5
   */
  static importDocument(filePath) {
    return MNUtil.app.importDocument(filePath)
  }
  /**
   * 该方法会弹出文件选择窗口以选择要导入的文档
   * @returns {string} 返回文件md5
   */
  static async importPDFFromFile(){
    let docPath = await MNUtil.importFile("com.adobe.pdf")
    return this.importDocument(docPath)
  }
  static imageFromBase64(base64,type = "png"){
    let data = this.dataFromBase64(base64,type)
    let image = UIImage.imageWithData(data)
    return image
  }
  static dataFromBase64(base64,type = undefined){
    if (base64.startsWith("data:")) {//如果是data url，则直接获取
      let data = NSData.dataWithContentsOfURL(MNUtil.genNSURL(base64))
      return data
    }
    if (type) {
      switch (type) {
        case "pdf":
          let pdfData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:application/pdf;base64,"+base64))
          return pdfData
        case "png":
          let pngData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:image/png;base64,"+base64))
          return pngData
        case "jpg":
        case "jpeg":
          let jpegData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:image/jpeg;base64,"+base64))
          return jpegData
        default:
          break;
      }
    }
    //没有指定类型，且不是data url，则认为是application/octet-stream
    let url = MNUtil.genNSURL("data:application/octet-stream;base64,"+base64)
    return NSData.dataWithContentsOfURL(url)
  }
  /**
   * 从base64导入pdf
   * @param {string} pdfBase64 pdf的base64字符串,可以是纯base64也可以是data url
   * @param {object} option 选项
   * @returns {string} 返回文件md5
   */
  static async importPDFFromBase64(pdfBase64,option = {}){
    let pdfData = this.dataFromBase64(pdfBase64)
    if ("filePath" in option) {
      this.writeDataToFile(pdfData,option.filePath)
      let md5 = this.importDocument(option.filePath)
      return md5
    }
    let fileName = option.fileName || ("imported_"+Date.now()+".pdf")
    let folder = option.folder || MNUtil.tempFolder()
    let filePath = folder.nativePath + fileName
    this.writeDataToFile(pdfData,filePath)
    let md5 = this.importDocument(filePath)
    return md5
  }
  /**
   * 该方法会弹出文件选择窗口以选择要导入的文档
   * @returns {string} 返回文件md5
   */
  static async importPDFFromData(pdfData){
    let docPath = await MNUtil.importFile("com.adobe.pdf")
    return this.importDocument(docPath)
  }
  /**
   * 该方法会弹出文件选择窗口以选择要导入的文档,并直接在指定学习集中打开
   * @returns {string} 返回文件md5
   */
  static async importPDFFromFileAndOpen(notebookId){
    let docPath = await MNUtil.importFile("com.adobe.pdf")
    let md5 = this.importDocument(docPath)
    MNUtil.openDoc(md5,notebookId)
    return md5
  }
  static toggleExtensionPanel(){
    this.studyController.toggleExtensionPanel()
  }
  /**
   * 
   * @param {string} path 
   * @returns {boolean}
   */
  static isfileExists(path) {
    return NSFileManager.defaultManager().fileExistsAtPath(path)
  }
  /**
   * 
   * @param {string} path 
   * @returns {boolean}
   */
  static fileExists(path) {
    return NSFileManager.defaultManager().fileExistsAtPath(path)
  }
  /**
   * Generates a frame object with the specified x, y, width, and height values.
   * 
   * This method creates a frame object with the provided x, y, width, and height values.
   * If any of these values are undefined, it displays a HUD message indicating the invalid parameter
   * and sets the value to 10 as a default.
   * 
   * @param {number} x - The x-coordinate of the frame.
   * @param {number} y - The y-coordinate of the frame.
   * @param {number} width - The width of the frame.
   * @param {number} height - The height of the frame.
   * @returns {{x: number, y: number, width: number, height: number}} The frame object with the specified dimensions.
   */
  static genFrame(x, y, width, height) {
    if (x === undefined) {
        this.showHUD("无效的参数: x");
        x = 10;
    }
    if (y === undefined) {
        this.showHUD("无效的参数: y");
        y = 10;
    }
    if (width === undefined) {
        this.showHUD("无效的参数: width");
        // this.copyJSON({x:x,y:y,width:width,height:height})
        width = 10;
    }
    if (height === undefined) {
        this.showHUD("无效的参数: height");
        height = 10;
    }
    return { x: x, y: y, width: width, height: height };
  }
  static setFrame(view,x,y,width,height){
    view.frame = {x:x,y:y,width:width,height:height}
  }
  /**
   *
   * @param {DocumentController} docController
   * @returns
   */
  static genSelection(docController){
    let selection = {onSelection:true,docController:docController}
    //无论是选中文字还是框选图片，都可以拿到图片。而文字则不一定
    let image = docController.imageFromSelection()
    if (image) {
      selection.image = image
      selection.isText = docController.isSelectionText
      if (docController.selectionText) {
        selection.text = docController.selectionText
      }
      selection.docMd5 = docController.docMd5
      selection.pageIndex = docController.currPageIndex
      return selection
    }
    return {onSelection:false}

  }
  static parseWinRect(winRect) {
    let rectArr = winRect.replace(/{/g, '').replace(/}/g, '').replace(/\s/g, '').split(',')
    let X = Number(rectArr[0])
    let Y = Number(rectArr[1])
    let H = Number(rectArr[3])
    let W = Number(rectArr[2])
    return this.genFrame(X, Y, W, H)
  }
  static async animate(func,time = 0.2) {
    return new Promise((resolve, reject) => {
      UIView.animateWithDurationAnimationsCompletion(time,func,()=>(resolve()))
    })

  }
  static checkSender(sender,window = this.currentWindow){
    return this.app.checkNotifySenderInWindow(sender, window)
  }
  /**
   * 
   * @param {number} seconds 
   * @returns 
   */
  static async delay (seconds) {
    return new Promise((resolve, reject) => {
      NSTimer.scheduledTimerWithTimeInterval(seconds, false, function () {
        resolve()
      })
    })
  }
  static crash(){
    this.studyView.frame = {x:undefined}
  }
  /**
   *
   * @param {UIView} view
   */
  static isDescendantOfStudyView(view){
    return view.isDescendantOfView(this.studyView)
  }
  /**
   *
   * @param {UIView} view
   */
  static isDescendantOfCurrentWindow(view){
    return view.isDescendantOfView(this.currentWindow)
  }
  static addObserver(observer,selector,name){
    if (!observer.notifications) {
      observer.notifications = [name]
    }else{
      observer.notifications.push(name)
    }
    NSNotificationCenter.defaultCenter().addObserverSelectorName(observer, selector, name);
  }
  static addObservers(observer,kv){

    let keys = Object.keys(kv)
    if (!observer.notifications) {
      observer.notifications = keys
    }else{
      let allNotifications = observer.notifications.concat(keys)
      observer.notifications = MNUtil.unique(allNotifications)
    }
    observer.notifications = keys
    for (let i = 0; i < keys.length; i++) {
      let name = keys[i]
      let selector = kv[name]
      NSNotificationCenter.defaultCenter().addObserverSelectorName(observer, selector, name);
    }
  }
  static addObserverForPopupMenuOnNote(observer,selector){
    this.addObserver(observer, selector, "PopupMenuOnNote")
  }
  static addObserverForClosePopupMenuOnNote(observer,selector){
    this.addObserver(observer, selector, "ClosePopupMenuOnNote")
  }
  static addObserverForPopupMenuOnSelection(observer,selector){
    this.addObserver(observer, selector, "PopupMenuOnSelection")
  }
  static addObserverForClosePopupMenuOnSelection(observer,selector){
    this.addObserver(observer, selector, "ClosePopupMenuOnSelection")
  }
  static addObserverForUITextViewTextDidBeginEditing(observer,selector){
    this.addObserver(observer, selector, "UITextViewTextDidBeginEditingNotification")
  }
  static addObserverForUITextViewTextDidEndEditing(observer,selector){
    this.addObserver(observer, selector, "UITextViewTextDidEndEditingNotification")
  }
  static addObserverForCloudKeyValueStoreDidChange(observer,selector){
    this.addObserver(observer, selector, "NSUbiquitousKeyValueStoreDidChangeExternallyNotificationUI")
  }
  static addObserverForProcessNewExcerpt(observer,selector){
    this.addObserver(observer, selector, "ProcessNewExcerpt")
  }
  static addObserverForAddonBroadcast(observer,selector){
    this.addObserver(observer, selector, "AddonBroadcast")
  }
  static addObserverForUIPasteboardChanged(observer,selector){
    this.addObserver(observer, selector, "UIPasteboardChangedNotification")
  }

  static removeObserver(observer,name){
    if (!name) {
      return
    }
    NSNotificationCenter.defaultCenter().removeObserverName(observer, name);
    observer.notifications = observer.notifications.filter(item=>{
      return item !== name;
    })
  }
  /**
   * 
   * @param {string} observer 
   * @param {Array<String>} notifications
   */
  static removeObservers(observer,notifications = undefined) {
    if (notifications && notifications.length) {
      notifications.forEach(notification=>{
        NSNotificationCenter.defaultCenter().removeObserverName(observer, notification);
      })
      observer.notifications = observer.notifications.filter(item=>{
        return !notifications.includes(item);
      })
    }else{//删除所有observer
      let allNotifications = observer.notifications;
      allNotifications.forEach(notification=>{
        NSNotificationCenter.defaultCenter().removeObserverName(observer, notification);
      })
      observer.notifications = observer.notifications.filter(item=>{
        return !allNotifications.includes(item);
      })
    }
  }
  static removeObserverForPopupMenuOnNote(observer){
    this.removeObserver(observer, "PopupMenuOnNote")
  }
  static removeObserverForClosePopupMenuOnNote(observer){
    this.removeObserver(observer, "ClosePopupMenuOnNote")
  }
  static removeObserverForPopupMenuOnSelection(observer){
    this.removeObserver(observer, "PopupMenuOnSelection")
  }
  static removeObserverForClosePopupMenuOnSelection(observer){
    this.removeObserver(observer, "ClosePopupMenuOnSelection")
  }
  static removeObserverForUITextViewTextDidBeginEditing(observer){
    this.removeObserver(observer, "UITextViewTextDidBeginEditingNotification")
  }
  static removeObserverForUITextViewTextDidEndEditing(observer){
    this.removeObserver(observer, "UITextViewTextDidEndEditingNotification")
  }
  static removeObserverForCloudKeyValueStoreDidChange(observer){
    this.removeObserver(observer, "NSUbiquitousKeyValueStoreDidChangeExternallyNotificationUI")
  }
  static removeObserverForProcessNewExcerpt(observer){
    this.removeObserver(observer, "ProcessNewExcerpt")
  }
  static removeObserverForAddonBroadcast(observer){
    this.removeObserver(observer, "AddonBroadcast")
  }
  static removeObserverForUIPasteboardChanged(observer){
    this.removeObserver(observer, "UIPasteboardChangedNotification")
  }
  static _lastRefreshAddonCommandsTime = 0
  static _needRefreshAddonCommands = false//用于处理频繁调用refreshAddonCommands的情况
  /**
   * 刷新addon命令状态,如果上次刷新时间小于100ms，则延迟0.1s再刷新
   * 如果上次刷新时间大于100ms，则直接刷新
   */
  static refreshAddonCommands(){
    let now = Date.now();
    let sinceLastRefresh = now - this._lastRefreshAddonCommandsTime;
    if ((sinceLastRefresh) < 100) {
      this._needRefreshAddonCommands = true
      MNUtil.delay(0.1).then(()=>{
        //这里并非直接阻止刷新，而是增加一个延迟，并通过_needRefreshAddonCommands进行状态控制
        //如果刷新的需求提前被触发，则不需要再进行刷新，类似将多次刷新组合在一起的延时操作，此时实际的延迟小于100ms
        //因此实际上每次刷新都会被满足，只不过可能会增加一个不超过100ms的延迟
        if (!this._needRefreshAddonCommands) {
          return
        }
        this.studyController.refreshAddonCommands()
        this._lastRefreshAddonCommandsTime = Date.now()
        this._needRefreshAddonCommands = false
      })
      return
    }
    //如果上次刷新时间大于100ms，则直接刷新，没有延迟
    this._lastRefreshAddonCommandsTime = now
    this._needRefreshAddonCommands = false
    this.studyController.refreshAddonCommands()
  }
  static _lastRefreshAfterDBChangedTime = 0
  static _needRefreshAfterDBChanged = false//用于处理频繁调用refreshAfterDBChanged的情况
  static refreshAfterDBChanged(notebookId = this.currentNotebookId){
    let now = Date.now();
    let sinceLastRefresh = now - this._lastRefreshAfterDBChangedTime;
    if ((sinceLastRefresh) < 100) {
      this._needRefreshAfterDBChanged = true
      MNUtil.delay(0.1).then(()=>{
        if (!this._needRefreshAfterDBChanged) {
          return
        }
        this.app.refreshAfterDBChanged(notebookId)
      })
      return
    }
    this._lastRefreshAfterDBChangedTime = now
    this._needRefreshAfterDBChanged = false
    this.app.refreshAfterDBChanged(notebookId)
  }
  static getLatestSelection(checkStatus = false){
    let latestSelection = undefined
    if (this.focusHistory.length > 0) {
      latestSelection = this.focusHistory.at(-1)
      if (checkStatus) {//检查上次记录的选择是否依然存在，如果存在，则返回最新的选择，否则返回undefined
        let selection = undefined
        let type = latestSelection.type
        switch (type) {
          case "text":
            selection = this.currentSelection
            if (selection.onSelection && selection.isText) {
              return latestSelection
            }
            return undefined
          case "image":
            selection = this.currentSelection
            if (selection.onSelection && !selection.isText) {
              return latestSelection
            }
            return undefined
          case "note":
            if (this.noteExists(latestSelection.noteId)) {
              let focusNote = MNNote.getFocusNote()
              if (focusNote && focusNote.noteId === latestSelection.noteId) {
                return latestSelection
              }
              return undefined
            }
            return undefined
        }
      }
      return latestSelection
    }
    return undefined
  }
  /**
   * Focuses a note in the mind map by its ID with an optional delay.
   * 
   * This method attempts to focus a note in the mind map by its ID. If the note is not in the current notebook,
   * it displays a HUD message indicating that the note is not in the current notebook. If a delay is specified,
   * it waits for the specified delay before focusing the note.
   * 
   * @param {string} noteId - The ID of the note to focus.
   * @param {number} [delay=0] - The delay in seconds before focusing the note.
   */
  static focusNoteInMindMapById(noteId,delay=0){
  try {
    let note = this.getNoteById(noteId)
    if (note.notebookId && note.notebookId !== this.currentNotebookId) {
      this.showHUD("Note not in current notebook")
      return
    }
    if (delay) {
      this.delay(delay).then(()=>{
        this.studyController.focusNoteInMindMapById(noteId)
      })
    }else{
      this.studyController.focusNoteInMindMapById(noteId)
    }

  } catch (error) {
    MNUtil.addErrorLog(error, "focusNoteInMindMapById")
  }
  }
  static focusNoteInFloatMindMapById(noteId,delay = 0){
    if (delay) {
      this.delay(delay).then(()=>{
        this.studyController.focusNoteInFloatMindMapById(noteId)
      })
    }else{
      this.studyController.focusNoteInFloatMindMapById(noteId)
    }
  }
  static focusNoteInDocumentById(noteId,delay = 0){
    if (delay) {
      this.delay(delay).then(()=>{
        this.studyController.focusNoteInDocumentById(noteId)
      })
    }else{
      this.studyController.focusNoteInDocumentById(noteId)
    }
  }
  /**
   * 
   * @param {string} jsonString 
   * @returns {boolean}
   */
  static isValidJSON(jsonString){
    // return NSJSONSerialization.isValidJSONObject(result)
     try{
         var json = JSON.parse(jsonString);
         if (json && typeof json === "object") {
             return true;
         }
     }catch(e){
         return false;
     }
     return false;
  }
  /**
   * 
   * @param {string} jsonString 
   * @returns {object|undefined}
   */
static getValidJSON(jsonString,debug = false) {
  try {
    if (typeof jsonString === "object") {
      return jsonString
    }
    return JSON.parse(jsonString)
  } catch (error) {
    try {
      return JSON.parse(jsonrepair(jsonString))
    } catch (error) {
      let errorString = error.toString()
      try {
        if (errorString.startsWith("Unexpected character \"{\" at position")) {
          return JSON.parse(jsonrepair(jsonString+"}"))
        }
        return {}
      } catch (error) {
        debug && this.addErrorLog(error, "getValidJSON", jsonString)
        return {}
      }
    }
  }
}
  /**
   * Merges multiple consecutive whitespace characters into a single space, except for newlines.
   * 
   * This method processes the input string to replace multiple consecutive whitespace characters
   * (excluding newlines) with a single space. It also ensures that multiple consecutive newlines
   * are reduced to a single newline. The resulting string is then trimmed of any leading or trailing
   * whitespace.
   * 
   * @param {string} str - The input string to be processed.
   * @returns {string} The processed string with merged whitespace.
   */
  static mergeWhitespace(str) {
      if (!str) {
        return "";
      }
      // 1. 替换为标准空格
      // 2. 将多个连续的换行符替换为单个换行符
      // 3. 将其它空白符（除了换行符）替换为单个空格
      var tempStr = str.replace(/&nbsp;/g, ' ').replace(/\n+/g, '\n\n').replace(/[\r\t\f\v\s]+/g, ' ').trim()
      // var tempStr = str.replace(/\n+/g, '\n').replace(/[\r\t\f\v ]+/g, ' ').trim()
      return tempStr;
  }
  static undo(notebookId = this.currentNotebookId){
    UndoManager.sharedInstance().undo()
    this.refreshAfterDBChanged(notebookId)

  }
  static redo(notebookId = this.currentNotebookId){
    UndoManager.sharedInstance().redo()
    this.refreshAfterDBChanged(notebookId)
  }
  /**
   * Groups the specified function within an undo operation for the given notebook.
   * 
   * This method wraps the provided function within an undo operation for the specified notebook.
   * It ensures that the function's changes can be undone as a single group. After the function is executed,
   * it refreshes the application to reflect the changes.
   * 
   * @param {Function} f - The function to be executed within the undo group.
   * @param {string} [notebookId=this.currentNotebookId] - The ID of the notebook for which the undo group is created.
   */
  static undoGrouping(f,notebookId = this.currentNotebookId){
    UndoManager.sharedInstance().undoGrouping(
      String(Date.now()),
      notebookId,
      f
    )
    this.refreshAfterDBChanged(notebookId)
  }
  /**
   * Groups the specified function within an undo operation for the given notebook.
   * 
   * This method wraps the provided function within an undo operation for the specified notebook.
   * It ensures that the function's changes can be undone as a single group. After the function is executed,
   * it refreshes the application to reflect the changes.
   * 
   * @param {Function} f - The function to be executed within the undo group.
   * @param {string} [notebookId=this.currentNotebookId] - The ID of the notebook for which the undo group is created.
   */
  static undoGroupingNotRefresh(f,notebookId = this.currentNotebookId){
    UndoManager.sharedInstance().undoGrouping(
      String(Date.now()),
      notebookId,
      f
    )
  }
  static getNoteColorHex(colorIndex){
    let theme = MNUtil.app.currentTheme
    let colorConfig = {
      Default:["#ffffb4","#ccfdc4","#b4d1fb","#f3aebe","#ffff54","#75fb4c","#55bbf9","#ea3323","#ef8733","#377e47","#173dac","#be3223","#ffffff","#dadada","#b4b4b4","#bd9edc"],
      Dark:["#a0a071","#809f7b","#71839e","#986d77","#a0a032","#479e2c","#33759c","#921c12","#96551c","#204f2c","#0c266c","#771e14","#a0a0a0","#898989","#717171","#77638a"],
      Gary:["#d2d294","#a8d1a1","#94accf","#c88f9d","#d2d244","#5fcf3d","#459acd","#c0281b","#c46f28","#2c683a","#12328e","#9c281c","#d2d2d2","#b4b4b4","#949494","#9c82b5"]
    }
    let colorHexes = (theme in colorConfig)?colorConfig[theme]:colorConfig["Default"]
    if (colorIndex !== undefined && colorIndex >= 0) {
      return colorHexes[colorIndex]
    }
    return "#ffffff"
  }
  static getImage(path,scale=2) {
    if (!this.isfileExists(path)) {
      console.log("getImage not exists",path)
      return undefined
    }
    return UIImage.imageWithDataScale(NSData.dataWithContentsOfFile(path), scale)
  }
  /**
   * 
   * @param {string} path 
   * @returns {NSData}
   */
  static getFile(path) {
    if (this.isfileExists(path)) {
      return NSData.dataWithContentsOfFile(path)
    }
    return undefined
  }
  /**
   * Extracts the file name from a full file path.
   * 
   * This method takes a full file path as input and extracts the file name by finding the last occurrence
   * of the '/' character and then taking the substring from that position to the end of the string.
   * 
   * @param {string} fullPath - The full path of the file.
   * @returns {string} The extracted file name.
   */
  static getFileName(fullPath) {
      // 找到最后一个'/'的位置
      let lastSlashIndex = fullPath.lastIndexOf('/');

      // 从最后一个'/'之后截取字符串，得到文件名
      let fileName = fullPath.substring(lastSlashIndex + 1);

      return fileName;
  }
  static getMediaByHash(hash) {
    let image = this.db.getMediaByHash(hash)
    return image
  }
  /**
   * 左 0, 下 1，3, 上 2, 右 4
   * @param {*} sender
   * @param {object[]} commandTable
   * @param {number} width
   * @param {number} preferredPosition
   * @returns
   */
  static getPopoverAndPresent(sender,commandTable,width=100,preferredPosition=2) {
    let position = preferredPosition
    var menuController = MenuController.new();
    menuController.commandTable = commandTable
    // menuController.sections = [commandTable,commandTable]
    menuController.rowHeight = 35;
    menuController.preferredContentSize = {
      width: width,
      height: menuController.rowHeight * menuController.commandTable.length
    };
    //左 0
    //下 1，3
    //上 2
    //右 4

    var popoverController = new UIPopoverController(menuController);
    let targetView = this.studyView
    var r = sender.convertRectToView(sender.bounds,targetView);
    // MNUtil.showHUD("message"+preferredPosition)
    switch (preferredPosition) {
      case 0:
        if (r.x < 50) {
          position = 4
        }
        break;
      case 1:
      case 3:
        if (r.y+r.height > targetView.frame.height - 50) {
          position = 2
        }
        break;
      case 2:
        if (r.y < 50) {
          position = 3
        }
        break;
      case 4:
        if (r.x+r.width > targetView.frame.width - 50) {
          position = 0
        }
        break;
      default:
        break;
    }
    popoverController.presentPopoverFromRect(r, targetView, position, true);
    return popoverController
  }
  /**
   *
   * @param {string} name
   * @param {*} userInfo
   */
  static postNotification(name,userInfo) {
    NSNotificationCenter.defaultCenter().postNotificationNameObjectUserInfo(name, this.currentWindow, userInfo)
  }
  /**
   * Parses a 6/8-digit hexadecimal color string into a color object.
   * 
   * @param {string} hex - The 6/8-digit hexadecimal color string to parse.
   * @returns {object} An object with the following properties: `color` (the parsed color string), and `opacity` (the opacity of the color).
   */
  static parseHexColor(hex) {
    // 检查输入是否是有效的6位16进制颜色字符串
    if (typeof hex === 'string' && hex.length === 7) {
          return {
              color: hex,
              opacity: 1
          };
    }
    // 检查输入是否是有效的8位16进制颜色字符串
    if (typeof hex !== 'string' || !/^#([0-9A-Fa-f]{8})$/.test(hex)) {
        throw new Error('Invalid 8-digit hexadecimal color');
    }

    // 提取红色、绿色、蓝色和不透明度的16进制部分
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const a = parseInt(hex.slice(7, 9), 16) / 255; // 转换为0到1的不透明度

    // 将RGB值转换为6位16进制颜色字符串
    const rgbHex = `#${hex.slice(1, 7)}`;

    return {
        color: rgbHex,
        opacity: parseFloat(a.toFixed(2)) // 保留2位小数
    };
  }
  static hexColorAlpha(hex,alpha=1.0) {
    let color = UIColor.colorWithHexString(hex)
    return alpha!==undefined?color.colorWithAlphaComponent(alpha):color
  }
  /**
   * 
   * @param {string} hex 
   * @returns {UIColor}
   */
  static hexColor(hex) {
    let colorObj = this.parseHexColor(hex)
    return MNUtil.hexColorAlpha(colorObj.color,colorObj.opacity)
  }
  static genNSURL(url) {
    return NSURL.URLWithString(url)
  }
  /**
   * 默认在当前学习集打开
   * @param {string} md5 
   * @param {string} notebookId
   */
  static openDoc(md5,notebookId=MNUtil.currentNotebookId){
    MNUtil.studyController.openNotebookAndDocument(notebookId, md5)
    let splitMode = MNUtil.docMapSplitMode
    if (splitMode === 0) {
      MNUtil.docMapSplitMode = 1
    }
  }
  /**
   * Converts NSData to a string.
   * @deprecated(use dataToString instead)
   * This method checks if the provided data object has a base64 encoding method. If it does,
   * it decodes the base64 data and converts it to a UTF-8 string. If the data object does not
   * have a base64 encoding method, it returns the data object itself.
   * 
   * @param {NSData} data - The data object to be converted to a string.
   * @returns {string} The converted string.
   */
  static data2string(data){
    if (data.base64Encoding) {
      let test = CryptoJS.enc.Base64.parse(data.base64Encoding())
      let textString = CryptoJS.enc.Utf8.stringify(test);
      return textString
    }else{
      return data
    }
  }
  static string2data(string){
    return NSData.dataWithStringEncoding(string, 4)
  }
  /**
   * Converts NSData to a string.
   * 
   * 
   * @param {NSData} data - The data object to be converted to a string.
   * @returns {string} The converted string.
   */
  static dataToString(data){
    if (data instanceof NSData) {
      return NSString.stringWithContentsOfData(data)
    }
    return data
  }
  /**
   * 
   * @param {object} object 
   * @returns 
   */
  static stringify(object){
    return JSON.stringify(object, undefined, 2)
  }
  /**
   * 
   * @param {string} path 
   * @returns {object|undefined}
   */
  static readJSON(path){
    if (!this.isfileExists(path)) {
      return undefined
    }
    let data = NSData.dataWithContentsOfFile(path)
    const res = NSJSONSerialization.JSONObjectWithDataOptions(
      data,
      1<<0
    )
    if (NSJSONSerialization.isValidJSONObject(res)) {
      return res
    }else{
      return undefined
    }
  }
  static writeJSON(path,object){
  try {
    let data = this.string2data(JSON.stringify(object, undefined, 2))
    this.writeDataToFile(data,path)
    return true
  } catch (error) {
    this.addErrorLog(error, "writeJSON")
    return false
  }
  }
  static readText(path){

    let data = NSData.dataWithContentsOfFile(path)
    return this.dataToString(data)
  }
  static writeText(path,string){
  try {
    let data = this.string2data(string)
    this.writeDataToFile(data,path)
    return true
    
  } catch (error) {
    this.addErrorLog(error, "writeText")
    return false
  }
  }
  static readTextFromUrlSync(url){
    let textData = NSData.dataWithContentsOfURL(this.genNSURL(url))
    let text = this.dataToString(textData)
    return text
  }
  static async readTextFromUrlAsync(url,option={}){
    // MNUtil.copy("readTextFromUrlAsync")
    let res = await MNConnection.fetch(url,option)
    if (!res.base64Encoding && "timeout" in res && res.timeout) {
      return undefined
    }
    let text = this.dataToString(res)
    return text
  }
  static isAddonRunning(addonName){
    let addonNameUpper = addonName.toUpperCase()
    switch (addonNameUpper) {
      case "SNIPASTE":
      case "MNSNIPASTE":
      case "MN SNIPASTE":
      case "MARGINNOTE.EXTENSION.MNSNIPASTE":
        return typeof snipasteUtils !== "undefined"
      case "WEBDAV":
      case "MNWEBDAV":
      case "MN WEBDAV":
      case "MARGINNOTE.EXTENSION.MNWEBDAV":
        return typeof webdavUtils !== "undefined"
      case "CHATAI":
      case "MNCHATAI":
      case "MN CHATAI":
      case "MARGINNOTE.EXTENSION.MNCHATGLM":
        return typeof chatAIUtils !== "undefined"
      case "BROWSER":
      case "MNBROWSER":
      case "MN BROWSER":
      case "MARGINNOTE.EXTENSION.MNBROWSER":
        return typeof browserUtils !== "undefined"
      case "TOOLBAR":
      case "MNTOOLBAR":
      case "MN TOOLBAR":
      case "MARGINNOTE.EXTENSION.MNTOOLBAR":
        return typeof toolbarUtils !== "undefined"
      case "MILKDOWN":
      case "MNMILKDOWN":
      case "MN MILKDOWN":
      case "MARGINNOTE.EXTENSION.MNMILKDOWN":
        return typeof milkdownUtils !== "undefined"
      case "EDITOR":
      case "MNEDITOR":
      case "MN EDITOR":
      case "MARGINNOTE.EXTENSION.MNEDITOR":
        return typeof editorUtils !== "undefined"
      case "CKEDITOR":
      case "MNCKEDITOR":
      case "MN CKEDITOR":
      case "MARGINNOTE.EXTENSION.MNCKEDITOR":
        return typeof ckeditorUtils !== "undefined"
      case "OCR":
      case "MNOCR":
      case "MN OCR":
      case "MARGINNOTE.EXTENSION.MNOCR":
        return typeof ocrUtils !== "undefined"
      case "AUTOSTYLE":
      case "MNAUTOSTYLE":
      case "MN AUTOSTYLE":
      case "MARGINNOTE.EXTENSION.MNAUTOSTYLE":
        return typeof autoUtils !== "undefined"
      default:
    }
    return false
  }
  /**
   * Encrypts or decrypts a string using XOR encryption with a given key.
   * 
   * This method performs XOR encryption or decryption on the input string using the provided key.
   * Each character in the input string is XORed with the corresponding character in the key,
   * repeating the key if it is shorter than the input string. The result is a new string
   * where each character is the XOR result of the original character and the key character.
   * 
   * @param {string} input - The input string to be encrypted or decrypted.
   * @param {string} key - The key used for XOR encryption or decryption.
   * @returns {string} The encrypted or decrypted string.
   */
  static xorEncryptDecrypt(input, key) {
  try {
    if (!key) throw new Error("Key cannot be empty"); // 提前校验key非空
    let output = [];
    let result = "";
    const chunkSize = 10000; // 分块大小（根据引擎性能调整）
    for (let i = 0; i < input.length; i++) {
      const code = input.charCodeAt(i) ^ key.charCodeAt(i % key.length);
      output.push(code);
      // 分块转换：当数组达到chunkSize时，批量生成字符串并清空临时数组
      if (output.length >= chunkSize) {
        result += String.fromCharCode(...output); // 用扩展运算符（...）代替apply，或直接循环拼接
        output = [];
      }
    }
    // 处理剩余的码点
    result += String.fromCharCode(...output);
    return result;
  } catch (error) {
    this.addErrorLog(error, "xorEncryptDecrypt");
    return undefined;
  }
}

  // static encrypt(text,key){
  //   var encrypted = CryptoJS.AES.encrypt(text, key).toString();
  //   return encrypted
  // }
  // static decrypt(text,key){
  //   var decrypted = CryptoJS.AES.decrypt(text, key).toString();
  //   var originalText = decrypted.toString(CryptoJS.enc.Utf8);
  //   return originalText
  // }
static md5FromBase64(base64Str) {
  // 1. 同样先补全
  let output = base64Str.replace(/-/g, '+').replace(/_/g, '/');
  switch (output.length % 4) {
    case 2: output += '=='; break;
    case 3: output += '='; break;
  }

  // 2. Base64 → WordArray（原始字节）
  const wordArray = CryptoJS.enc.Base64.parse(output);

  // 3. 直接算 MD5
  return CryptoJS.MD5(wordArray).toString(CryptoJS.enc.Hex);
}

static sha256FromBase64(base64Str) {
  // 1. 同样先补全
  let output = base64Str.replace(/-/g, '+').replace(/_/g, '/');
  switch (output.length % 4) {
    case 2: output += '=='; break;
    case 3: output += '='; break;
  }

  // 2. Base64 → WordArray（原始字节）
  const wordArray = CryptoJS.enc.Base64.parse(output);

  // 3. 直接算 SHA256
  return CryptoJS.SHA256(wordArray).toString(CryptoJS.enc.Hex);
}
  /**
   * 
   * @param {NSData|string} data 
   * @returns {string}
   */
  static MD5(data){
    if (typeof data === "string") {
      let md5 = CryptoJS.MD5(data).toString();
      return md5
    }
    if (data instanceof NSData) {
      let md5 = this.md5FromBase64(data.base64Encoding())
      return md5
    }
    return undefined
  }
  static getFileMD5(path){
    let data = NSData.dataWithContentsOfFile(path)
    return this.MD5(data)
  }
  static parseMNImageURL(MNImageURL){
    if (MNImageURL.includes("markdownimg/png/")) {
      let hash = MNImageURL.split("markdownimg/png/")[1]
      this.imageTypeCache[hash] = "png"
      return {
        hash: hash,
        type: "png",
        ext: "png"
      }
    }else if (MNImageURL.includes("markdownimg/jpeg/")) {
      let hash = MNImageURL.split("markdownimg/jpeg/")[1]
      this.imageTypeCache[hash] = "jpeg"
      return {
        hash: hash,
        type: "jpeg",
        ext: "jpg"
      }
    }
    return undefined
  }
  static replaceMNImagesWithBase64(markdown) {
  // if (/!\[.*?\]\((marginnote4app\:\/\/markdownimg\/png\/.*?)(\))/) {

  //   // ![image.png](marginnote4app://markdownimg/png/eebc45f6b237d8abf279d785e5dcda20)
  // }
try {
    // 处理 Markdown 字符串，替换每个 base64 图片链接
    const result = markdown.replace(this.MNImagePattern, (match, MNImageURL,p2) => {
      // 你可以在这里对 base64Str 进行替换或处理
      // shouldOverWritten = true
      let imageConfig = this.parseMNImageURL(MNImageURL)
      let hash = imageConfig.hash
      let imageData = MNUtil.getMediaByHash(hash)
      let imageBase64 = imageData.base64Encoding()
      // if (!imageData) {
      //   return match.replace(MNImageURL, hash+".png");
      // }
      // imageData.writeToFileAtomically(editorUtils.bufferFolder+hash+".png", false)
      return match.replace(MNImageURL, "data:image/"+imageConfig.type+";base64,"+imageBase64);
    });
  return result;
} catch (error) {
  this.addErrorLog(error, "replaceMNImagesWithBase64")
  return undefined
}
}

  static md2html(md){
    let tem = this.replaceMNImagesWithBase64(md)
    return marked.parse(tem.replace(/_{/g,'\\_\{').replace(/_\\/g,'\\_\\'))
  }
  /**
   * Escapes special characters in a string to ensure it can be safely used in JavaScript code.
   * 
   * This method escapes backslashes, backticks, template literal placeholders, carriage returns,
   * newlines, single quotes, and double quotes in the input string. The resulting string can be
   * safely used in JavaScript code without causing syntax errors.
   * 
   * @param {string} str - The input string to be escaped.
   * @returns {string} The escaped string.
   */
  static escapeString(str) {
    return str.replace(/\\/g, '\\\\') // Escape backslashes
              .replace(/\`/g, '\\`') // Escape backticks
              .replace(/\$\{/g, '\\${') // Escape template literal placeholders
              .replace(/\r/g, '\\r') // Escape carriage returns
              .replace(/\n/g, '\\n') // Escape newlines
              .replace(/'/g, "\\'")   // Escape single quotes
              .replace(/"/g, '\\"');  // Escape double quotes
  }
  static getLocalDataByKey(key) {
    return NSUserDefaults.standardUserDefaults().objectForKey(key)
  }
  /**
   * 从本地获取数据，如果本地没有，则从备份文件中获取，如果备份文件也没有，则使用默认值
   * @param {string} key 
   * @param {any} defaultValue 
   * @param {string} backUpFile 
   * @returns 
   */
  static getLocalDataByKeyWithDefaultAndBackup(key,defaultValue,backUpFile) {
    let value = NSUserDefaults.standardUserDefaults().objectForKey(key)
    if (value === undefined) {
      if (backUpFile && this.isfileExists(backUpFile)) {//需要检查备份文件
        let backupConfig = this.readJSON(backUpFile)
        if (backupConfig && Object.keys(backupConfig).length > 0) {
          return backupConfig
        }
      }
      NSUserDefaults.standardUserDefaults().setObjectForKey(defaultValue,key)
      return defaultValue
    }
    return value
  }
  static setLocalDataByKey(data, key) {
    NSUserDefaults.standardUserDefaults().setObjectForKey(data, key)
  }
  static getCloudDataByKey(key) {
    return NSUbiquitousKeyValueStore.defaultStore().objectForKey(key)
  }
  static setCloudDataByKey(data, key) {
    NSUbiquitousKeyValueStore.defaultStore().setObjectForKey(data, key)
  }

  /**
   *
   * @param {string | string[]} UTI
   * @returns
   */
  static async importFile(UTI){
    if (Array.isArray(UTI)) {
      return new Promise((resolve, reject) => {
        this.app.openFileWithUTIs(UTI,this.studyController,(path)=>{
          resolve(path)
        })
      })
    }else{
      return new Promise((resolve, reject) => {
        this.app.openFileWithUTIs([UTI],this.studyController,(path)=>{
          resolve(path)
        })
      })
    }
  }
  /**
   * 弹出文件选择窗口,选中json后直接返回对应的json对象
   * @returns {Object}
   */
  static async importJSONFromFile(){
    let path = await MNUtil.importFile("public.json")
    return this.readJSON(path)
  }
  static saveFile(filePath, UTI) {
    this.app.saveFileWithUti(filePath, UTI)
  }
  /**
   * 去重
   * @param {T[]} arr
   * @param {boolean} noEmpty
   * @returns {T[]}
   */
 static unique (arr, noEmpty = false){
  let ret = []
  if (arr.length <= 1) ret = arr
  else ret = Array.from(new Set(arr))
  if (noEmpty) ret = ret.filter(k => k)
  return ret
}
  /**
   * 
   * @param {undefined|string|MNNote|MbBookNote|NSData|UIImage} object 
   * @returns 
   */
  static typeOf(object){
    let type = typeof object
    switch (type) {
      case "undefined":
        return "undefined"
      case "string":
        if (/^marginnote\dapp:\/\/note\//.test(object.trim())) {
          return "NoteURL"
        }
        if (/^marginnote\dapp:\/\/tocNote\//.test(object.trim())) {
          return "TocNoteURL"
        }
        if (/^marginnote\dapp:\/\/notebook\//.test(object.trim())) {
          return "NotebookURL"
        }
        if (/^marginnote\dapp:\/\/book\//.test(object.trim())) {
          return "DocumentURL"
        }
        if (/^marginnote\dapp:\/\/page\//.test(object.trim())) {
          return "PageURL"
        }
        if (/^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/.test(object.trim())) {
          return "NoteId"
        }
        return "string"
      default:
        break;
    }
    if (object instanceof MNNote) {
      return "MNNote"
    }
    if (object instanceof MNNotebook) {
      return "MNNotebook"
    }
    if (object instanceof NSData) {
      let fileType = this.getFileTypeFromData(object)
      if (fileType !== 'unknown') {
        return fileType
      }
      return "NSData"
    }
    if (object instanceof UIImage) {
      return "UIImage"
    }
    if (object instanceof MNComment) {
      return "MNComment"
    }
    if (object instanceof MNDocument) {
      return "MNDocument"
    }
    if (object.noteId) {
      return "MbBookNote"
    }
    if (object instanceof NSURL) {
      return "NSURL"
    }
    if (object instanceof NSURLRequest) {
      return "NSURLRequest"
    }
    if (object instanceof UIView) {
      if (object instanceof UIWebView) {
        return "UIWebView"
      }
      return "UIView"
    }
    if ("title" in object || "content" in object || "excerptText" in object) {
      return "NoteConfig"
    }

    return typeof object

  }
  static getNoteId(note){
    let noteId
    switch (this.typeOf(note)) {
      case "MbBookNote":
        noteId = note.noteId
        break;
      case "NoteURL":
        noteId = this.getNoteIdByURL(note)
        break;
      case "NoteId":
      case 'string':
        noteId = note
        break;
      default:
        this.showHUD("MNUtil.getNoteId: Invalid param")
        return undefined
    }
    return noteId
  }
  /**
   * 注意即使是纯文档模式，也可能是allMap（返回0）,且studyMode为2,所以需要使用currentNotebook.flags来判断
   * @returns {number}
   * allMap = 0,
   * half = 1,
   * allDoc = 2
   */
  static get docMapSplitMode(){
    let notebookType = this.currentNotebook.flags
    if (notebookType === 1) {//文档模式下，直接返回当前文档控制器的焦点笔记
      //此时studyController.docMapSplitMode为0，但实际上为纯文档模式，应返回2
      return 2
    }
    return this.studyController.docMapSplitMode
  }
  static set docMapSplitMode(mode){
    let notebookType = this.currentNotebook.flags
    if (notebookType === 1) {//文档模式
      //纯文档模式下不允许调整docMapSplitMode
      return
    }
    this.studyController.docMapSplitMode = mode
  }
  /**
   * @param {UIView} view 
   * @returns {Array<{x:number,y:number,width:number,height:number}>}
   */
  static getSubviewsFrame(view){
    let subviews = view.subviews
    let subviewsFrame = subviews.map(subview=>{
      return subview.frame
    })
    return subviewsFrame
  }
  /**
   * 
   * @param {UITextView} textView 
   */
  static getMindmapview(textView){
    let mindmapView
    if (textView.isDescendantOfView(this.mindmapView)) {
      mindmapView = this.mindmapView
      return mindmapView
    }else{
      try {
        let targetMindview = textView.superview.superview.superview.superview.superview
        let targetStudyview = targetMindview.superview.superview.superview
        if (targetStudyview === this.studyView) {
          mindmapView = targetMindview
          if (!mindmapView.selViewLst) {
            return undefined
          }
          this.floatMindMapView = mindmapView
          return mindmapView
        }
        return undefined
      } catch (error) {
        return undefined
      }
    }
  }
  /**
   * Retrieves the image data from the current document controller or other document controllers if the document map split mode is enabled.
   * 
   * This method checks for image data in the current document controller's selection. If no image is found, it checks the focused note within the current document controller.
   * If the document map split mode is enabled, it iterates through all document controllers to find the image data. If a pop-up selection info is available, it also checks the associated document controller.
   * 
   * @param {boolean} [checkImageFromNote=false] - Whether to check the focused note for image data.
   * @param {boolean} [checkDocMapSplitMode=false] - Whether to check other document controllers if the document map split mode is enabled.
   * @returns {NSData|undefined} The image data if found, otherwise undefined.
   */
  static getDocImage(checkImageFromNote=false,checkDocMapSplitMode=false){
  try {

    let docMapSplitMode = this.docMapSplitMode
    if (checkDocMapSplitMode && !docMapSplitMode) {
      return undefined
    }
    let imageData = this.currentDocController.imageFromSelection()
    if (imageData) {
      return imageData
    }
    if (checkImageFromNote) {
      imageData = this.currentDocController.imageFromFocusNote()
    }
    if (imageData) {
      return imageData
    }
    // MNUtil.showHUD("message"+this.docControllers.length)
    if (docMapSplitMode) {//不为0则表示documentControllers存在
      let imageData
      let docNumber = this.docControllers.length
      for (let i = 0; i < docNumber; i++) {
        const docController = this.docControllers[i];
        imageData = docController.imageFromSelection()
        if (!imageData && checkImageFromNote) {
          imageData = docController.imageFromFocusNote()
        }
        if (imageData) {
          return imageData
        }
      }
    }
    if (this.popUpSelectionInfo) {
      let docController = this.popUpSelectionInfo.docController
      let imageData = docController.imageFromSelection()
      if (imageData) {
        return imageData
      }
      if (checkImageFromNote) {
        imageData = docController.imageFromFocusNote()
      }
      if (imageData) {
        return imageData
      }
    }
    return undefined
  } catch (error) {
    this.addErrorLog(error, "getDocImage")
    return undefined
  }
  }
  /**
 * 从 Markdown 文本中提取链接
 * @param {string} markdownContent - Markdown 格式的字符串
 * @returns {Array<{title: string, link: string}>} - 包含 title 和 link 的对象数组
 */
static extractMarkdownLinks(markdownContent) {
  // 正则表达式解释：
  // \[([^\]]*)\] : 匹配 [ ] 及其内部的文字（作为 title），([^\]]*) 表示捕获除了 ] 之外的任意字符
  // \(([^)]*)\) : 匹配 ( ) 及其内部的文字（作为 link），([^)]*) 表示捕获除了 ) 之外的任意字符
  // g : 全局匹配
  const regex = /\[([^\]]*)\]\(([^)]*)\)/g;
  
  const results = [];
  let match;

  // 使用 exec 循环匹配所有结果
  while ((match = regex.exec(markdownContent)) !== null) {
    // match.index 是当前匹配到的 [ 开始的位置
    // 检查是否是图片：如果 [ 前面有一个 !，则它是图片语法 ![alt](src)，应当跳过
    if (match.index > 0 && markdownContent[match.index - 1] === '!') {
      continue;
    }

    results.push({
      title: match[1], // 第一个捕获组：方括号内的内容
      link: match[2]   // 第二个捕获组：圆括号内的内容
    });
  }

  return results;
}

  /**
   * 
   * @param {"AddToReview"|"AddToTOC"|"BackupDB"|"BindSplit"|"BookTOC"|"BookPageList"|"BookMarkList"|"BookSketchList"|"BookCardList"|"BookSearch"|"BookPageFlip"|"BookPageScroll"|"BookPageNumber"|"BookMarkAdd"|"BookMarkRemove"|"ClearTemp"|"ClearFormat1"|"ClearFormat2"|"CommonCopy"|"CollapseExtend"|"ContinueExcerpt"|"DBVaults"|"DraftList"|"EditAddTitle"|"EditAddText"|"EditAppendComment"|"EditArrangeNotes"|"EditUndo"|"EditRedo"|"EditCut"|"EditCopy"|"EditCopyLink"|"EditDeleteNote"|"EditDocLayers"|"EditPaste"|"EditPDFPages"|"EditMarkdown"|"EditTextBox"|"EditTextMode"|"EditImageBox"|"EditGroupNotes"|"EditLinkNotes"|"EditMultiSel"|"EditMergeNotes"|"EditOcclusion"|"EditOutlineIncLevel"|"EditOutlineDecLevel"|"EditReference"|"EditSelAll"|"EditTagNote"|"EditUnmergeNote"|"EditColorNoteIndex0"|"EditColorNoteIndex1"|"EditColorNoteIndex2"|"EditColorNoteIndex3"|"EditColorNoteIndex4"|"EditColorNoteIndex5"|"EditColorNoteIndex6"|"EditColorNoteIndex7"|"EditColorNoteIndex8"|"EditColorNoteIndex9"|"EditColorNoteIndex10"|"EditColorNoteIndex11"|"EditColorNoteIndex12"|"EditColorNoteIndex13"|"EditColorNoteIndex14"|"EditColorNoteIndex15"|"ExcerptToolSettings"|"ExcerptToolSelect"|"ExcerptToolCustom0"|"ExcerptToolCustom1"|"ExcerptToolCustom2"|"ExcerptToolCustom3"|"ExcerptToolSketch"|"EmphasisCloze"|"ExportPKG"|"ExportVault"|"ExportMapPDF"|"ExportDocPDF"|"ExportOmni"|"ExportWord"|"ExportMind"|"ExportAnki"|"ExtendSplit"|"ExtendMargin"|"ExtendPopup"|"ExpandExtend"|"FocusNote"|"FocusParent"|"FoldHighlight"|"FullTextSearch"|"FlashcardsPlay"|"FlashcardsStop"|"FlashcardFlip"|"FlashcardLocal"|"FlashcardAgain"|"FlashcardHard"|"FlashcardGood"|"FlashcardEasy"|"FlashcardStarred"|"FlashcardSpeech"|"GlobalBranchStyle"|"GoBack"|"GoForward"|"GoiCloud"|"GoManual"|"GoNewFeatures"|"GoSettings"|"GoUserGuide"|"HideSketch"|"HighlightShortcut1"|"HighlightShortcut2"|"HighlightShortcut3"|"HighlightShortcut4"|"InAppPurchase"|"InsertBlank"|"ManageDocs"|"MergeTo"|"MindmapSnippetMode"|"NotebookOutline"|"NotebookOutlineEdit"|"NewSiblingNote"|"NewChildNote"|"NewParentNote"|"OpenTrash"|"OpenExtensions"|"PdfCrop"|"RemoveFromMap"|"SendToMap"|"ShareLicenses"|"SharePackage"|"SplitBook"|"SyncMindMapToBook"|"SyncBookToMindMap"|"SyncWindowPos"|"SyncDeletion"|"SetAsEmphasis"|"SetCloneCopyMode"|"SetCommentHighlight"|"SetRefCopyMode"|"SetTitleHighlight"|"SourceHighlight"|"SnippetMode"|"SelBranchStyle0"|"SelBranchStyle1"|"SelBranchStyle2"|"SelBranchStyle3"|"SelBranchStyle4"|"SelBranchStyle60"|"SelBranchStyle61"|"SelBranchStyle64"|"SelBranchStyle7"|"SelBranchStyle100"|"SelectBranch"|"ShowSketch"|"TabNextFile"|"TabPrevFile"|"TextToTitle"|"Translate"|"ToggleAddFile"|"ToggleBookLeft"|"ToggleBookBottom"|"ToggleCards"|"ToggleDocument"|"ToggleExpand"|"ToggleFullDoc"|"ToggleSplit"|"ToggleSidebar"|"ToggleTabsBar"|"ToggleTextLink"|"ToggleMindMap"|"ToggleMoreSettings"|"ToggleReview"|"ToggleResearch"|"UIStatusURL"|"ViewCollapseRows"|"ViewCollapseAll"|"ViewDocCardGroup"|"ViewExpandAll"|"ViewExpandLevel0"|"ViewExpandLevel1"|"ViewExpandLevel2"|"ViewExpandLevel3"|"ViewExpandLevel4"|"ViewExpandLevel5"|"ViewExpandLevel6"|"ViewExpandLevel7"|"ViewExpandRows"|"ViewMapCardGroup"|"ZoomToFit"} command 
   */
  static excuteCommand(command){
    let urlPre = "marginnote4app://command/"
    if (command) {
      let url = urlPre+command
      this.openURL(url)
      return
    }
  }
  /**
   * 
   * @param {"AddToReview"|"AddToTOC"|"BackupDB"|"BindSplit"|"BookTOC"|"BookPageList"|"BookMarkList"|"BookSketchList"|"BookCardList"|"BookSearch"|"BookPageFlip"|"BookPageScroll"|"BookPageNumber"|"BookMarkAdd"|"BookMarkRemove"|"ClearTemp"|"ClearFormat1"|"ClearFormat2"|"CommonCopy"|"CollapseExtend"|"ContinueExcerpt"|"DBVaults"|"DraftList"|"EditAddTitle"|"EditAddText"|"EditAppendComment"|"EditArrangeNotes"|"EditUndo"|"EditRedo"|"EditCut"|"EditCopy"|"EditCopyLink"|"EditDeleteNote"|"EditDocLayers"|"EditPaste"|"EditPDFPages"|"EditMarkdown"|"EditTextBox"|"EditTextMode"|"EditImageBox"|"EditGroupNotes"|"EditLinkNotes"|"EditMultiSel"|"EditMergeNotes"|"EditOcclusion"|"EditOutlineIncLevel"|"EditOutlineDecLevel"|"EditReference"|"EditSelAll"|"EditTagNote"|"EditUnmergeNote"|"EditColorNoteIndex0"|"EditColorNoteIndex1"|"EditColorNoteIndex2"|"EditColorNoteIndex3"|"EditColorNoteIndex4"|"EditColorNoteIndex5"|"EditColorNoteIndex6"|"EditColorNoteIndex7"|"EditColorNoteIndex8"|"EditColorNoteIndex9"|"EditColorNoteIndex10"|"EditColorNoteIndex11"|"EditColorNoteIndex12"|"EditColorNoteIndex13"|"EditColorNoteIndex14"|"EditColorNoteIndex15"|"ExcerptToolSettings"|"ExcerptToolSelect"|"ExcerptToolCustom0"|"ExcerptToolCustom1"|"ExcerptToolCustom2"|"ExcerptToolCustom3"|"ExcerptToolSketch"|"EmphasisCloze"|"ExportPKG"|"ExportVault"|"ExportMapPDF"|"ExportDocPDF"|"ExportOmni"|"ExportWord"|"ExportMind"|"ExportAnki"|"ExtendSplit"|"ExtendMargin"|"ExtendPopup"|"ExpandExtend"|"FocusNote"|"FocusParent"|"FoldHighlight"|"FullTextSearch"|"FlashcardsPlay"|"FlashcardsStop"|"FlashcardFlip"|"FlashcardLocal"|"FlashcardAgain"|"FlashcardHard"|"FlashcardGood"|"FlashcardEasy"|"FlashcardStarred"|"FlashcardSpeech"|"GlobalBranchStyle"|"GoBack"|"GoForward"|"GoiCloud"|"GoManual"|"GoNewFeatures"|"GoSettings"|"GoUserGuide"|"HideSketch"|"HighlightShortcut1"|"HighlightShortcut2"|"HighlightShortcut3"|"HighlightShortcut4"|"InAppPurchase"|"InsertBlank"|"ManageDocs"|"MergeTo"|"MindmapSnippetMode"|"NotebookOutline"|"NotebookOutlineEdit"|"NewSiblingNote"|"NewChildNote"|"NewParentNote"|"OpenTrash"|"OpenExtensions"|"PdfCrop"|"RemoveFromMap"|"SendToMap"|"ShareLicenses"|"SharePackage"|"SplitBook"|"SyncMindMapToBook"|"SyncBookToMindMap"|"SyncWindowPos"|"SyncDeletion"|"SetAsEmphasis"|"SetCloneCopyMode"|"SetCommentHighlight"|"SetRefCopyMode"|"SetTitleHighlight"|"SourceHighlight"|"SnippetMode"|"SelBranchStyle0"|"SelBranchStyle1"|"SelBranchStyle2"|"SelBranchStyle3"|"SelBranchStyle4"|"SelBranchStyle60"|"SelBranchStyle61"|"SelBranchStyle64"|"SelBranchStyle7"|"SelBranchStyle100"|"SelectBranch"|"ShowSketch"|"TabNextFile"|"TabPrevFile"|"TextToTitle"|"Translate"|"ToggleAddFile"|"ToggleBookLeft"|"ToggleBookBottom"|"ToggleCards"|"ToggleDocument"|"ToggleExpand"|"ToggleFullDoc"|"ToggleSplit"|"ToggleSidebar"|"ToggleTabsBar"|"ToggleTextLink"|"ToggleMindMap"|"ToggleMoreSettings"|"ToggleReview"|"ToggleResearch"|"UIStatusURL"|"ViewCollapseRows"|"ViewCollapseAll"|"ViewDocCardGroup"|"ViewExpandAll"|"ViewExpandLevel0"|"ViewExpandLevel1"|"ViewExpandLevel2"|"ViewExpandLevel3"|"ViewExpandLevel4"|"ViewExpandLevel5"|"ViewExpandLevel6"|"ViewExpandLevel7"|"ViewExpandRows"|"ViewMapCardGroup"|"ZoomToFit"} command 
   */
  static executeCommand(command){
    let urlPre = "marginnote4app://command/"
    if (command) {
      let url = urlPre+command
      this.openMarginNoteURL(url)
      return
    }
  }
  /**
   * executeCommand不占用执行时长，但可能会导致多个命令堆在一起执行，这时候可以尝试executeCommandAsync
   * @param {"AddToReview"|"AddToTOC"|"BackupDB"|"BindSplit"|"BookTOC"|"BookPageList"|"BookMarkList"|"BookSketchList"|"BookCardList"|"BookSearch"|"BookPageFlip"|"BookPageScroll"|"BookPageNumber"|"BookMarkAdd"|"BookMarkRemove"|"ClearTemp"|"ClearFormat1"|"ClearFormat2"|"CommonCopy"|"CollapseExtend"|"ContinueExcerpt"|"DBVaults"|"DraftList"|"EditAddTitle"|"EditAddText"|"EditAppendComment"|"EditArrangeNotes"|"EditUndo"|"EditRedo"|"EditCut"|"EditCopy"|"EditCopyLink"|"EditDeleteNote"|"EditDocLayers"|"EditPaste"|"EditPDFPages"|"EditMarkdown"|"EditTextBox"|"EditTextMode"|"EditImageBox"|"EditGroupNotes"|"EditLinkNotes"|"EditMultiSel"|"EditMergeNotes"|"EditOcclusion"|"EditOutlineIncLevel"|"EditOutlineDecLevel"|"EditReference"|"EditSelAll"|"EditTagNote"|"EditUnmergeNote"|"EditColorNoteIndex0"|"EditColorNoteIndex1"|"EditColorNoteIndex2"|"EditColorNoteIndex3"|"EditColorNoteIndex4"|"EditColorNoteIndex5"|"EditColorNoteIndex6"|"EditColorNoteIndex7"|"EditColorNoteIndex8"|"EditColorNoteIndex9"|"EditColorNoteIndex10"|"EditColorNoteIndex11"|"EditColorNoteIndex12"|"EditColorNoteIndex13"|"EditColorNoteIndex14"|"EditColorNoteIndex15"|"ExcerptToolSettings"|"ExcerptToolSelect"|"ExcerptToolCustom0"|"ExcerptToolCustom1"|"ExcerptToolCustom2"|"ExcerptToolCustom3"|"ExcerptToolSketch"|"EmphasisCloze"|"ExportPKG"|"ExportVault"|"ExportMapPDF"|"ExportDocPDF"|"ExportOmni"|"ExportWord"|"ExportMind"|"ExportAnki"|"ExtendSplit"|"ExtendMargin"|"ExtendPopup"|"ExpandExtend"|"FocusNote"|"FocusParent"|"FoldHighlight"|"FullTextSearch"|"FlashcardsPlay"|"FlashcardsStop"|"FlashcardFlip"|"FlashcardLocal"|"FlashcardAgain"|"FlashcardHard"|"FlashcardGood"|"FlashcardEasy"|"FlashcardStarred"|"FlashcardSpeech"|"GlobalBranchStyle"|"GoBack"|"GoForward"|"GoiCloud"|"GoManual"|"GoNewFeatures"|"GoSettings"|"GoUserGuide"|"HideSketch"|"HighlightShortcut1"|"HighlightShortcut2"|"HighlightShortcut3"|"HighlightShortcut4"|"InAppPurchase"|"InsertBlank"|"ManageDocs"|"MergeTo"|"MindmapSnippetMode"|"NotebookOutline"|"NotebookOutlineEdit"|"NewSiblingNote"|"NewChildNote"|"NewParentNote"|"OpenTrash"|"OpenExtensions"|"PdfCrop"|"RemoveFromMap"|"SendToMap"|"ShareLicenses"|"SharePackage"|"SplitBook"|"SyncMindMapToBook"|"SyncBookToMindMap"|"SyncWindowPos"|"SyncDeletion"|"SetAsEmphasis"|"SetCloneCopyMode"|"SetCommentHighlight"|"SetRefCopyMode"|"SetTitleHighlight"|"SourceHighlight"|"SnippetMode"|"SelBranchStyle0"|"SelBranchStyle1"|"SelBranchStyle2"|"SelBranchStyle3"|"SelBranchStyle4"|"SelBranchStyle60"|"SelBranchStyle61"|"SelBranchStyle64"|"SelBranchStyle7"|"SelBranchStyle100"|"SelectBranch"|"ShowSketch"|"TabNextFile"|"TabPrevFile"|"TextToTitle"|"Translate"|"ToggleAddFile"|"ToggleBookLeft"|"ToggleBookBottom"|"ToggleCards"|"ToggleDocument"|"ToggleExpand"|"ToggleFullDoc"|"ToggleSplit"|"ToggleSidebar"|"ToggleTabsBar"|"ToggleTextLink"|"ToggleMindMap"|"ToggleMoreSettings"|"ToggleReview"|"ToggleResearch"|"UIStatusURL"|"ViewCollapseRows"|"ViewCollapseAll"|"ViewDocCardGroup"|"ViewExpandAll"|"ViewExpandLevel0"|"ViewExpandLevel1"|"ViewExpandLevel2"|"ViewExpandLevel3"|"ViewExpandLevel4"|"ViewExpandLevel5"|"ViewExpandLevel6"|"ViewExpandLevel7"|"ViewExpandRows"|"ViewMapCardGroup"|"ZoomToFit"} command 
   */
  static async executeCommandAsync(command){
    let urlPre = "marginnote4app://command/"
    if (command) {
      let url = urlPre+command
      await this.openURLOptionsCompletionHandler(url)
      return
    }
  }
  /**
   *
   * @param {number[]} arr
   * @param {string} type
   */
  static sort(arr,type="increment"){
    let arrToSort = arr
    switch (type) {
      case "decrement":
        arrToSort.sort((a, b) => b - a);
        break;
      case "increment":
        arrToSort.sort((a, b) => a - b);
        break;
      default:
        break;
    }
    return [...new Set(arrToSort)]
  }
  /**
   * Displays an input dialog with a title, subtitle, and a list of items.
   * 
   * This method shows an input dialog with the specified title and subtitle. It allows the user to input text and select from a list of items.
   * The method returns a promise that resolves with an object containing the input text and the index of the button clicked by the user.
   * 
   * @param {string} title - The main title of the input dialog.
   * @param {string} subTitle - The subtitle of the input dialog.
   * @param {string[]} items - The list of items to display in the dialog.
   * @param {object} options - The options for the input dialog.
   * @param {string} options.placeholder - The placeholder for the input text field.
   * @param {string} options.default - The default value for the input text field.
   * @param {number} options.clearButtonMode - The clear button mode for the input text field.
   * @returns {Promise<{input:string,button:number}>} A promise that resolves with an object containing the input text and the button index.
   */
  static async input(title,subTitle="",items = [this.cancelString,this.confirmString],options=undefined) {
    if (MNOnAlert) {
      return
    }
    MNOnAlert = true
    return new Promise(async(resolve, reject) => {
      let alertview = UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
        title,subTitle,2,items[0],items.slice(1),
        (alert, buttonIndex) => {
          let res = {input:alert.textFieldAtIndex(0).text,button:buttonIndex}
          MNOnAlert = false
          resolve(res)
        }
      )
      if (options) {
        try {
          await MNUtil.delay(0.5)
          let textField = alertview.textFieldAtIndex(0)
          while (!textField) {
            await MNUtil.delay(0.1)
            textField = alertview.textFieldAtIndex(0)
          }
          if ("placeholder" in options) {
            textField.text = options.placeholder
          }
          if ("default" in options) {
            textField.text = options.default
            let clearButtonMode = options.clearButtonMode ?? 1
            textField.clearButtonMode = clearButtonMode
          }
        } catch (error) {
          MNUtil.addErrorLog(error, "MNUtil.input")
        }
      }
    })
  }
  /**
   * Displays an input dialog with a title, subtitle, and a list of items.
   * 
   * This method shows an input dialog with the specified title and subtitle. It allows the user to input text and select from a list of items.
   * The method returns a promise that resolves with an object containing the input text and the index of the button clicked by the user.
   * 
   * @param {string} title - The main title of the input dialog.
   * @param {string} subTitle - The subtitle of the input dialog.
   * @param {string[]} items - The list of items to display in the dialog.
   * @returns {Promise<{input:string,button:number}>} A promise that resolves with an object containing the input text and the button index.
   */
  static async userInput(title,subTitle="",items = [this.cancelString,this.confirmString],options=undefined) {
    if (MNOnAlert) {
      return
    }
    MNOnAlert = true
    return new Promise(async (resolve, reject) => {
      let alertview = UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
        title,subTitle,2,items[0],items.slice(1),
        (alert, buttonIndex) => {
          let res = {input:alert.textFieldAtIndex(0).text,button:buttonIndex}
          MNOnAlert = false
          resolve(res)
        }
      )
      if (options) {
        try {
          await MNUtil.delay(0.5)
          let textField = alertview.textFieldAtIndex(0)
          while (!textField) {
            await MNUtil.delay(0.1)
            textField = alertview.textFieldAtIndex(0)
          }
          if ("default" in options) {
            textField.text = options.default
            let clearButtonMode = options.clearButtonMode ?? 1
            textField.clearButtonMode = clearButtonMode
          }else if ("placeholder" in options) {
            textField.text = options.placeholder
            let clearButtonMode = options.clearButtonMode ?? 1
            textField.clearButtonMode = clearButtonMode
          }
        } catch (error) {
          this.addErrorLog(error, "MNUtil.input")
        }
      }
    })
  }


  /**
   * 注意这里的code需要是字符串
   * @param {string|number} code
   * @returns {string}
   */
  static getStatusCodeDescription(code){
  try {
    let des = {
    "200": "OK",
    "400": "Bad Request",
    "401": "Unauthorized",
    "402": "Payment Required",
    "403": "Forbidden",
    "404": "Not Found",
    "405": "Method Not Allowed",
    "406": "Not Acceptable",
    "407": "Proxy Authentication Required",
    "408": "Request Timeout",
    "409": "Conflict",
    "410": "Gone",
    "411": "Length Required",
    "412": "Precondition Failed",
    "413": "Payload Too Large",
    "414": "URI Too Long",
    "415": "Unsupported Media Type",
    "416": "Range Not Satisfiable",
    "417": "Expectation Failed",
    "418": "I'm a teapot",
    "421": "Misdirected Request",
    "422": "Unprocessable Entity",
    "423": "Locked",
    "424": "Failed Dependency",
    "425": "Too Early",
    "426": "Upgrade Required",
    "428": "Precondition Required",
    "429": "Too Many Requests",
    "431": "Request Header Fields Too Large",
    "451": "Unavailable For Legal Reasons",
    "500": "Internal Server Error",
    "501": "Not Implemented",
    "502": "Bad Gateway",
    "503": "Service Unavailable",
    "504": "Gateway Timeout",
    "505": "HTTP Version Not Supported",
    "506": "Variant Also Negotiates",
    "507": "Insufficient Storage",
    "508": "Loop Detected",
    "510": "Not Extended",
    "511": "Network Authentication Required",
    "525": "SSL handshake failed",
  }
  if (typeof code === "number") {
    if (code === 0) {
      return "Response is null"
    }
    let codeString = ""+code
    if (codeString in des) {
      return (codeString+": "+des[codeString])
    }
    return ""
  }
  if (code in des) {
    return (code+": "+des[code])
  }
  return ""
  } catch (error) {
    this.addErrorLog(error, "getStatusCodeDescription")
  }
  }
  /**
   * 
   * @param {string} template 
   * @param {object} config 
   * @returns {string}
   */
  static render(template,config){
    let output = mustache.render(template,config)
    return output
  }
  /**
   * 
   * @param {number} value 
   * @param {number} min 
   * @param {number} max 
   * @returns {number}
   */
  static constrain(value, min, max) {
    if (min > max) {
      return Math.min(Math.max(value, max), min);
    }
    return Math.min(Math.max(value, min), max);
  }
  /**
   * max为10
   * @param {number} index 
   * @returns 
   */
  static emojiNumber(index){
    let emojiIndices = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    return emojiIndices[index]
  }
  static tableItem(title,object,selector,params,checked=false) {
    return {title:title,object:object,selector:selector,param:params,checked:checked}
  }
  static createJsonEditor(htmlPath){
    let jsonEditor = new UIWebView(MNUtil.genFrame(0, 0, 100, 100));
    try {
    
    jsonEditor.loadFileURLAllowingReadAccessToURL(
      NSURL.fileURLWithPath(this.mainPath + '/pages/jsoneditor.html'),
      NSURL.fileURLWithPath(this.mainPath + '/')
    );
    } catch (error) {
      this.addErrorLog(error, "createJsonEditor")
    }
    return jsonEditor
  }
  static deepEqual(obj1, obj2,keysToIgnore) {
    if (obj1 === obj2) return true;

    if (typeof obj1 !== 'object' || obj1 === null ||
        typeof obj2 !== 'object' || obj2 === null) {
        return false;
    }

    let keys1 = Object.keys(obj1);
    let keys2 = Object.keys(obj2);
    if (keysToIgnore && keysToIgnore.length) {
      keys1 = keys1.filter(k => !keysToIgnore.includes(k));
      keys2 = keys2.filter(k => !keysToIgnore.includes(k));
    }
    if (keys1.length !== keys2.length) return false;

    for (let key of keys1) {
        if (!keys2.includes(key)) {
            return false;
        }
        if (keysToIgnore && keysToIgnore.length && keysToIgnore.includes(key)) {
          continue
        }
        if (!this.deepEqual(obj1[key], obj2[key])) {
          return false;
        }
    }
    return true;
  }
  static readCloudKey(key){
    let cloudStore = NSUbiquitousKeyValueStore.defaultStore()
    if (cloudStore) {
      return cloudStore.objectForKey(key)
    }else{
      return undefined
    }
  }
  static setCloudKey(key,value){
    let cloudStore = NSUbiquitousKeyValueStore.defaultStore()
    if (cloudStore) {
      cloudStore.setObjectForKey(value,key)
    }
  }
  /**
   * 
   * @param {string[]} arr 
   * @param {string} element 
   * @param {string} direction 
   * @returns {string[]}
   */
  static moveElement(arr, element, direction) {
      // 获取元素的索引
      var index = arr.indexOf(element);
      if (index === -1) {
          this.showHUD('Element not found in array');
          return;
      }
      switch (direction) {
          case 'up':
              if (index === 0) {
                  this.showHUD('Element is already at the top');
                  return;
              }
              // 交换元素位置
              [arr[index], arr[index - 1]] = [arr[index - 1], arr[index]];
              break;
          case 'down':
              if (index === arr.length - 1) {
                  this.showHUD('Element is already at the bottom');
                  return;
              }
              // 交换元素位置
              [arr[index], arr[index + 1]] = [arr[index + 1], arr[index]];
              break;
          case 'top':
              // 移除元素
              arr.splice(index, 1);
              // 添加到顶部
              arr.unshift(element);
              break;
          case 'bottom':
              // 移除元素
              arr.splice(index, 1);
              // 添加到底部
              arr.push(element);
              break;
          default:
              this.showHUD('Invalid direction');
              break;
      }
      return arr
  }
  /**
   * 
   * @returns {string}
   */
  static UUID() {
    return NSUUID.UUID().UUIDString()
  }
  static isPureMNImages(markdown) {
    try {
      // 匹配 base64 图片链接的正则表达式
      let res = markdown.match(this.MNImagePattern)
      if (res && res.length) {
        return markdown === res[0]
      }else{
        return false
      }
    } catch (error) {
      this.addErrorLog(error, "isPureMNImages")
      return false
    }
  }
  static hasMNImages(markdown) {
    try {
      if (!markdown) {
        return false
      }
      if (!markdown.trim()) {
        return false
      }
      // 匹配 base64 图片链接的正则表达式，支持png和jpeg
      // let res = markdown.match(this.MNImagePattern)
      // let link = markdown.match(MNImagePattern)
      // console.log(link);
      
      // MNUtil.copyJSON({"a":link,"b":markdown})
      return markdown.match(this.MNImagePattern)?true:false
    } catch (error) {
      this.addErrorLog(error, "hasMNImages")
      return false
    }
  }
  static getMNImageURL(hash,type = "png"){
    if (hash in this.imageTypeCache) {
      type = this.imageTypeCache[hash]
    }
    return `marginnote4app://markdownimg/${type}/${hash}`
  }
  /**
   * 只返回第一个图片
   * @param {string} markdown 
   * @returns {NSData}
   */
  static getMNImageFromMarkdown(markdown) {
    try {
      let imageId = this.getMNImageIdFromMarkdown(markdown)
      if (imageId) {
        let imageData = MNUtil.getMediaByHash(imageId)
        return imageData
      }
      return undefined
    } catch (error) {
      this.addErrorLog(error, "getMNImageFromMarkdown")
      return undefined
    }
  }
  /**
   * 返回所有图片
   * @param {string} markdown 
   * @returns {NSData[]}
   */
  static getMNImagesFromMarkdown(markdown) {
    let imageIds = this.getMNImageIdsFromMarkdown(markdown)
    if (imageIds.length) {
      let imageDatas = imageIds.map(imageId=>MNUtil.getMediaByHash(imageId))
      return imageDatas
    }
    return []
  }
  /**
   * 只返回第一个图片
   * @param {string} markdown 
   * @returns {string[]}
   */
  static getMNImageIdsFromMarkdown(markdown) {
  try {

    let imageIds = []
    markdown.replace(this.MNImagePattern, (match, MNImageURL,p2) => {
      // 你可以在这里对 base64Str 进行替换或处理
      // shouldOverWritten = true
      let imageConfig = this.parseMNImageURL(MNImageURL)
      let hash = imageConfig.hash
      imageIds.push(hash)
      return ""
    });
    return imageIds
    
  } catch (error) {
    this.addErrorLog(error, "getMNImageIdsFromMarkdown")
    return undefined
  }
  }
  /**
   * 只返回第一个图片
   * @param {string} markdown 
   * @returns {string}
   */
  static getMNImageIdFromMarkdown(markdown) {
  try {
    let imageIds = this.getMNImageIdsFromMarkdown(markdown)
    if (imageIds.length) {
      return imageIds[0]
    }
    return undefined
  } catch (error) {
    this.addErrorLog(error, "getMNImageIdFromMarkdown")
    return undefined
  }
  }
  /**
   * 
   * @param {MNNote} note 
   */
  static getNoteObject(note,opt={first:true}) {
    try {
    if (!note) {
      return undefined
    }
      
    let noteConfig = config
    noteConfig.id = note.noteId
    if (opt.first) {
      noteConfig.notebook = {
        id:note.notebookId,
        name:this.getNoteBookById(note.notebookId).title,
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
    if (note.docMd5 && this.getDocById(note.docMd5)) {
      noteConfig.docName = this.getFileName(this.getDocById(note.docMd5).pathFile) 
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
      this.showHUD(error)
      return undefined
    }
  }
  static getDateObject(){
    let dateObject = {
      now:new Date(Date.now()).toLocaleString(),
      tomorrow:new Date(Date.now()+86400000).toLocaleString(),
      yesterday:new Date(Date.now()-86400000).toLocaleString(),
      year:new Date().getFullYear(),
      month:new Date().getMonth()+1,
      day:new Date().getDate(),
      hour:new Date().getHours(),
      minute:new Date().getMinutes(),
      second:new Date().getSeconds()
    }
    return dateObject
  }
  /**
   * 递归解析列表项及其子列表
   * @param {object[]} items 
   * @returns 
   */
  static processList(items) {
  return items.map(item => {
    // 提取当前列表项文本（忽略内部格式如粗体、斜体）
    const text = item.text.trim();
    const node = { name: text, children: [] ,type:item.type};

    // 检查列表项内部是否包含子列表（嵌套结构）
    const subLists = item.tokens.filter(t => t.type === 'list');
    if (subLists.length) {
      node.hasList = true
      node.listText = subLists[0].raw
      node.listStart = subLists[0].start
      node.listOrdered = subLists[0].ordered
      node.name = item.tokens[0].text
    }
    subLists.forEach(subList => {
      // 递归处理子列表的 items
      node.children.push(...this.processList(subList.items));
    });

    return node;
  });
}
static getUnformattedText(token) {
  if ("tokens" in token && token.tokens.length === 1) {
    return this.getUnformattedText(token.tokens[0])
  }else{
    return token.text
  }
}
/**
 * 构建树结构（整合标题和列表解析）
 * @param {object[]} tokens 
 * @returns 
 */
  static buildTree(tokens) {
  const root = { name: '中心主题', children: [] };
  const stack = [{ node: root, depth: 0 }]; // 用栈跟踪层级
  let filteredTokens = tokens.filter(token => token.type !== 'space' && token.type !== 'hr')

  filteredTokens.forEach((token,index) => {
    let current = stack[stack.length - 1];

    if (token.type === 'heading') {
      // 标题层级比栈顶浅，则回退栈到对应层级
      while (stack.length > 1 && token.depth <= current.depth) {
        stack.pop();
        current = stack[stack.length - 1]
      }
      const newNode = { name: this.getUnformattedText(token), children: [] ,type:'heading'};
      current.node.children.push(newNode);
      stack.push({ node: newNode, depth: token.depth });
    } else if (token.type === 'list') {
      // 处理列表（可能包含多级嵌套）
      const listNodes = this.processList(token.items);
      if(index && filteredTokens[index-1].type === 'paragraph'){
        if (current.node.type === 'paragraph') {
          stack.pop();
        }
        stack.push({ node: current.node.children.at(-1), depth: 100 });
        current = stack[stack.length - 1];
        // current.node.children.at(-1).hasList = true;
        // current.node.children.at(-1).listText = token.raw;
        // current.node.children.at(-1).listStart = token.start;
        // current.node.children.at(-1).ordered = token.ordered;
        // current.node.children.at(-1).children.push(...listNodes)
      }
      current.node.hasList = true;
      current.node.listText = token.raw;
      current.node.listStart = token.start;
      current.node.ordered = token.ordered;
      current.node.children.push(...listNodes);
      
    } else {
      if (token.type === 'paragraph' && current.node.type === 'paragraph') {
        stack.pop();
        current = stack[stack.length - 1];
      }
      current.node.children.push({ name: token.raw, raw: token.raw, children: [] ,type:token.type});
    }
  });
  return root;
}
  static markdown2AST(markdown){
    let tokens = marked.lexer(markdown)
    // MNUtil.copy(tokens)
    return this.buildTree(tokens)
  }
static extractHeadingNames(node) {
  try {
    

  let result = [];
  
  // 检查当前节点是否是 heading 类型
  if (node.type && node.type === 'heading') {
    result.push(node.name);
  }
  
  // 递归处理子节点
  if (node.children && node.children.length > 0) {
    for (const child of node.children) {
      result = result.concat(this.extractHeadingNames(child));
    }
  }
  
  return result;
  } catch (error) {
    this.addErrorLog(error, "extractHeadingNames")
    return []
  }
}
  /**
   * @param {string} markdown 
   * @returns {string[]}
   */
  static headingNamesFromMarkdown(markdown){
    let ast = this.markdown2AST(markdown)
    return this.extractHeadingNames(ast)
  }
static  containsMathFormula(markdownText) {
    // 正则表达式匹配单美元符号包裹的公式
    const inlineMathRegex = /\$[^$]+\$/;
    // 正则表达式匹配双美元符号包裹的公式
    const blockMathRegex = /\$\$[^$]+\$\$/;
    // 检查是否包含单美元或双美元符号包裹的公式
    return inlineMathRegex.test(markdownText) || blockMathRegex.test(markdownText);
}
static  containsUrl(markdownText) {
    // 正则表达式匹配常见的网址格式
    const urlPattern = /https?:\/\/[^\s]+|www\.[^\s]+/i;
    
    // 使用正则表达式测试文本
    return urlPattern.test(markdownText);
}

static removeMarkdownFormat(markdownStr) {
  return markdownStr
    // 移除加粗 ** ** 和 __ __
    .replace(/\*\*(\S(.*?\S)?)\*\*/g, '$1')
    .replace(/__(\S(.*?\S)?)__/g, '$1')
    // 移除斜体 * * 和 _ _
    .replace(/\*(\S(.*?\S)?)\*/g, '$1')
    .replace(/_(\S(.*?\S)?)_/g, '$1')
    // 移除删除线 ~~ ~~
    .replace(/~~(\S(.*?\S)?)~~/g, '$1')
    // 移除内联代码 ` `
    .replace(/`([^`]+)`/g, '$1')
    // 移除链接 [text](url)
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 移除图片 ![alt](url)
    .replace(/!\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 移除标题 # 和 ##
    .replace(/^#{1,6}\s+/gm, '')
    // 移除部分列表符号（*、-、+.）
    .replace(/^[\s\t]*([-*+]\.)\s+/gm, '')
    // 移除块引用 >
    .replace(/^>\s+/gm, '')
    // 移除水平线 ---
    .replace(/^[-*]{3,}/gm, '')
    // 移除HTML标签（简单处理）
    .replace(/<[^>]+>/g, '')
    // 合并多个空行
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
static getConfig(text){
  let hasMathFormula = this.containsMathFormula(text)
  if (hasMathFormula) {//存在公式内容
    if (/\:/.test(text)) {
      let splitedText = text.split(":")
      //冒号前有公式,则直接不设置标题,只设置excerpt且开启markdown
      if (this.containsMathFormula(splitedText[0])) {
        let config = {excerptText:text,excerptTextMarkdown:true}
        return config
      }
      //冒号前无公式,冒号后有公式
      if (this.containsMathFormula(splitedText[1])) {
        let config = {title:splitedText[0],excerptText:splitedText[1],excerptTextMarkdown:true}
        return config
      }
      let config = {title:splitedText[0],excerptText:splitedText[1]}
      return config
    }
    if (/\：/.test(text)) {
      let splitedText = text.split("：")
      //冒号前有公式,则直接不设置标题,只设置excerpt且开启markdown
      if (this.containsMathFormula(splitedText[0])) {
        let config = {excerptText:text,excerptTextMarkdown:true}
        return config
      }
      //冒号前无公式,冒号后有公式
      if (this.containsMathFormula(splitedText[1])) {
        let config = {title:splitedText[0],excerptText:splitedText[1],excerptTextMarkdown:true}
        return config
      }
      let config = {title:splitedText[0],excerptText:splitedText[1]}
      return config
    }
    
    let config = {excerptText:text,excerptTextMarkdown:true}
    return config
  }
  if (this.containsUrl(text)) {
    let config = {excerptText:text,excerptTextMarkdown:true}
    return config
  }
    if (/\:/.test(text)) {
      let splitedText = text.split(":")
      if (splitedText[0].length > 50) {
        let config = {excerptText:text}
        return config
      }
      let config = {title:splitedText[0],excerptText:splitedText[1]}
      return config
    }
    if (/\：/.test(text)) {
      let splitedText = text.split("：")
      if (splitedText[0].length > 50) {
        let config = {excerptText:text}
        return config
      }
      let config = {title:splitedText[0],excerptText:splitedText[1]}
      return config
    }
  if (text.length > 50) {
    return {excerptText:text}
  }
  return {title:text}
}
/**
 * 
 * @param {MNNote} note 
 * @param {Object} ast 
 */
static AST2Mindmap(note,ast,level = "all") {
try {
  if (ast.children && ast.children.length) {
    let hasList = ast.hasList
    let listOrdered = ast.listOrdered || ast.ordered
    ast.children.forEach((c,index)=>{
      if (c.type === 'hr') {
        return
      }
      let text = this.removeMarkdownFormat(c.name)
      // let text = c.name
      if (text.endsWith(":") || text.endsWith("：")) {
        text = text.slice(0,-1)
      }
      let config = this.getConfig(text)
      if ((text.startsWith('$') && text.endsWith('$')) || /\:/.test(text) || /：/.test(text)) {

      }else{
        if (c.children.length === 1 && !(/\:/.test(c.children[0].name) || /：/.test(c.children[0].name))) {
          if (text.endsWith(":") || text.endsWith("：")) {
            config = {excerptText:text+"\n"+c.children[0].name}
          }else{
            config = {title:text,excerptText:c.children[0].name}
          }
          let childNote = note.createChildNote(config)
          if (c.children[0].children.length) {
            this.AST2Mindmap(childNote,c.children[0])
          }
          return
        }
        if (c.children.length > 1 && c.children[0].type === 'paragraph' && c.children[1].type === 'heading') {
          if (text.endsWith(":") || text.endsWith("：")) {
            config = {excerptText:text+"\n"+c.children[0].name}
          }else{
            config = {title:text,excerptText:c.children[0].name}
          }
          c.children.shift()
        }
      }
      if (hasList && listOrdered) {
        if (ast.listStart == 0) {
          ast.listStart = 1
        }
        if (config.title) {
          config.title = (ast.listStart+index)+". "+config.title
        }else{
          config.excerptText = (ast.listStart+index)+". "+config.excerptText
        }
      }
      // MNUtil.showHUD("message")
      //继续创建子节点
      let childNote = note.createChildNote(config)
      this.AST2Mindmap(childNote,c)
    })
  }else{
    // MNUtil.showHUD("No children found")
  }
  } catch (error) {
  this.addErrorLog(error, "AST2Mindmap")
}
}
static hasBackLink(from,to){
  let fromNote = MNNote.new(from)
  let targetNote = MNNote.new(to)//链接到的卡片
  if (targetNote.linkedNotes && targetNote.linkedNotes.length > 0) {
    if (targetNote.linkedNotes.some(n=>n.noteid === fromNote.noteId)) {
      return true
    }
  }
  return false
}
static extractMarginNoteLinks(text) {
    // 正则表达式匹配 marginnote4app://note/ 后面跟着的 UUID 格式的链接
    const regex = /marginnote4app:\/\/note\/[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}/gi;
    
    // 使用 match 方法提取所有符合正则表达式的链接
    const links = text.match(regex);
    
    // 如果找到匹配的链接，返回它们；否则返回空数组
    return links || [];
}

/**
 * 
 * @param {string|number} color 
 * @returns {number}
 */
static getColorIndex(color){
    if (typeof color === 'string') {
      let colorMap = {
        "LIGHTYELLOW":0,
        "LIGHTGREEN":1,
        "LIGHTBLUE":2,
        "LIGHTRED":3,
        "YELLOW":4,
        "GREEN":5,
        "BLUE":6,
        "RED":7,
        "ORANGE":8,
        "LIGHTORANGE":8,
        "DARKGREEN":9,
        "DARKBLUE":10,
        "DARKRED":11,
        "DEEPRED":11,
        "WHITE":12,
        "LIGHTGRAY":13,
        "DARKGRAY":14,
        "PURPLE":15,
        "LIGHTPURPLE":15,
      }
      // let colors  = ["LightYellow", "LightGreen", "LightBlue", "LightRed","Yellow", "Green", "Blue", "Red", "Orange", "DarkGreen","DarkBlue", "DeepRed", "White", "LightGray","DarkGray", "Purple"]
      let index = colorMap[color.toUpperCase()]
      if (index !== -1) {
        return index
      }
      return -1
    } else {
      return color
    }

  }
/**
 * NSValue can't be read by JavaScriptCore, so we need to convert it to string.
 */
static NSValue2String(v) {
  return Database.transArrayToJSCompatible([v])[0]
}
/**
 * 
 * @param {NSValue} v 
 * @returns {CGSize}
 */
static NSValue2CGSize(v) {
  let sizeString = this.NSValue2String(v)
  let size = sizeString.match(/\d+/g).map(k => Number(k))
  return {width: size[0], height: size[1]}
}
/**
 * 
 * @param {NSValue} v 
 * @returns {CGRect}
 */
static NSValue2CGRect(v) {
  let rectString = this.NSValue2String(v)
  let rect = rectString.match(/\d+/g).map(k => Number(k))
  return {x: rect[0], y: rect[1], height: rect[2], width: rect[3]}
}
  /**
   * 
   * @param {string} str 
   * @returns {CGRect}
   */
  static CGRectString2CGRect(str) {
  const arr = str.match(/\d+\.?\d+/g).map(k => Number(k))
  return {
    x: arr[0],
    y: arr[1],
    height: arr[2],
    width: arr[3]
  }
}
static stringFromCharCode(char) {
  if (typeof char === 'string') {
    return String.fromCharCode(Number(char))
  }
  return String.fromCharCode(char)
}

/**
 * 模块功能：提取页面原始数据，并转化为易处理的 JS 对象
 * @param {MbBook} document 
 * @param {number} pageNo - 页码
 * @returns {Array} lines - 标准化的行对象数组
 */
static extractRawLines(pageNo,document=this.currentDocController.document) {
  if (!document) return [];
  // 结构：[ [charObj, charObj...], [charObj...] ... ]
const rawData = document.textContentsForPageNo(pageNo);
    if (!rawData || !rawData.length) return [];
    return rawData.reduce((acc, charObjs) => {
        if (!charObjs || !charObjs.length) return acc;
        // --- 核心修复：检测行内的大裂缝 (Column Gap) ---
        let currentSegment = {
            chars: [],
            startX: this.NSValue2CGRect(charObjs[0].rect).x
        };
        
        const segments = [currentSegment];
        
        for (let i = 0; i < charObjs.length; i++) {
            const charObj = charObjs[i];
            const rect = this.NSValue2CGRect(charObj.rect);
            
            // 如果不是第一个字，检查和上一个字的距离
            if (i > 0) {
                const prevRect = this.NSValue2CGRect(charObjs[i-1].rect);
                const gap = rect.x - (prevRect.x + prevRect.width);
                
                // 阈值：如果间距 > 20px，认为是分栏了
                // 这个阈值要比普通空格宽（普通空格通常 5-10px）
                if (gap > 20) {
                    // 结束当前段，开启新段
                    currentSegment = {
                        chars: [],
                        startX: rect.x
                    };
                    segments.push(currentSegment);
                }
            }
            currentSegment.chars.push(charObj);
        }
        // --- 将切分好的片段转为标准 Line 对象 ---
        segments.forEach(seg => {
            if (!seg.chars.length) return;
            
            const text = seg.chars.reduce((str, c) => str + (c.char ? String.fromCharCode(c.char) : ""), "").trim();
            if (!text) return;
            const firstRect = this.NSValue2CGRect(seg.chars[0].rect);
            const lastRect = this.NSValue2CGRect(seg.chars[seg.chars.length - 1].rect);
            const width = (lastRect.x + lastRect.width) - firstRect.x;
            acc.push({
                text,
                x: Math.round(firstRect.x),
                y: Math.round(firstRect.y),
                width: Math.round(width),
                height: firstRect.height,
                right: Math.round(firstRect.x + width), // 关键属性
                bottom: firstRect.y + firstRect.height
            });
        });
        return acc;
    }, []);
}
static analyzeLayout(lines) {
    if (!lines || lines.length < 10) {
        return { splitX: 0, isTwoColumn: false, standardLeftX: 0, standardRightX: 0 };
    }

    // 1. 基础数据准备
    const minX = Math.min(...lines.map(l => l.x));
    const maxX = Math.max(...lines.map(l => l.right));
    const pageWidth = maxX - minX;

    // 2. X 坐标归桶 (Binning)，找出所有候选栏目起点
    const xHistogram = {};
    lines.forEach(l => {
        // 排除特别宽的行（通常是通栏标题），它们不参与分栏判定
        if (l.width > pageWidth * 0.7) return;
        
        const bucket = Math.floor(l.x / 5) * 5; 
        xHistogram[bucket] = (xHistogram[bucket] || 0) + 1;
    });

    // 找出频率 > 5 的所有潜在起点，按 X 坐标排序（从左到右）
    const candidates = Object.keys(xHistogram)
        .map(x => parseInt(x))
        .filter(x => xHistogram[x] > 5)
        .sort((a, b) => a - b);

    // 3. 寻找最佳的双栏组合 (Best Column Pair)
    let bestPair = null;
    let maxScore = 0;

    // 遍历所有可能的两两组合
    for (let i = 0; i < candidates.length; i++) {
        for (let j = i + 1; j < candidates.length; j++) {
            const leftX = candidates[i];
            const rightX = candidates[j];
            
            // 3.1 间距检查
            // 两栏起点间距至少要是页面宽度的 1/4 (降低阈值以适应学术论文紧凑排版)
            // 同时也限制最大间距，防止误判极边缘的页码
            const stride = rightX - leftX;
            if (stride < pageWidth * 0.25 || stride > pageWidth * 0.8) continue;

            // 3.2 垂直重叠检查 (核心逻辑)
            // 找出属于左栏的行和属于右栏的行
            const leftLines = lines.filter(l => Math.abs(l.x - leftX) < 15 && l.width < pageWidth * 0.6);
            const rightLines = lines.filter(l => Math.abs(l.x - rightX) < 15 && l.width < pageWidth * 0.6);

            if (leftLines.length < 3 || rightLines.length < 3) continue;

            // 计算两组线的 Y 轴范围
            const lMinY = Math.min(...leftLines.map(l => l.y));
            const lMaxY = Math.max(...leftLines.map(l => l.bottom));
            const rMinY = Math.min(...rightLines.map(l => l.y));
            const rMaxY = Math.max(...rightLines.map(l => l.bottom));

            // 计算重叠高度
            const overlapStart = Math.max(lMinY, rMinY);
            const overlapEnd = Math.min(lMaxY, rMaxY);
            const overlapHeight = Math.max(0, overlapEnd - overlapStart);

            // 如果重叠高度太小（比如只是偶尔碰上），不算分栏
            if (overlapHeight < 50) continue;

            // 3.3 评分系统
            // 分数 = 重叠高度 * (左栏行数 + 右栏行数)
            // 我们倾向于选择重叠区域大、且行数多的组合（这样能排除 Header/Abstract 的干扰）
            const score = overlapHeight * (leftLines.length + rightLines.length);

            if (score > maxScore) {
                maxScore = score;
                bestPair = { leftX, rightX, leftLines, rightLines };
            }
        }
    }

    // 4. 生成结果
    if (bestPair) {
        // 计算分割线 SplitX
        // 找到左栏的最右边
        const leftMaxRight = Math.max(...bestPair.leftLines.map(l => l.right));
        // 找到右栏的最左边 (其实就是 rightX)
        const rightMinLeft = Math.min(...bestPair.rightLines.map(l => l.x));
        
        // 分割线取中间
        // 注意：有些紧凑排版 gap 只有 4-5px，所以取平均值最稳妥
        let splitX = (leftMaxRight + rightMinLeft) / 2;

        // 安全检查：如果计算出的 splitX 比右栏起点还大（数据异常），强制修正
        if (splitX >= bestPair.rightX) splitX = bestPair.rightX - 2;
        
        return {
            splitX: splitX,
            isTwoColumn: true,
            standardLeftX: bestPair.leftX,
            standardRightX: bestPair.rightX
        };
    }

    // 降级处理：单栏
    return {
        splitX: (minX + maxX) / 2,
        isTwoColumn: false,
        standardLeftX: minX,
        standardRightX: maxX
    };
}

/**
 * 进阶版：自动处理单双栏混合排版 (Smart Layout Detection)
 * 
 * 逻辑：
 * 1. 提取所有行的坐标 (x, y, width, height, text)。
 * 2. 计算页面中线 (midX)。
 * 3. 识别“通栏行”(Span Line)：即同时覆盖中线左侧和右侧的行（如标题）。
 * 4. 利用通栏行将页面垂直切分为多个“区块 (Section)”。
 * 5. 对每个区块内部：
 *    - 如果没有通栏行，则按左右分栏排序 (左栏先读，右栏后读)。
 *    - 如果是通栏行，直接加入结果。
 * @param {MbBook} doc 
 * @param {number} pageNo，第一页为1
 * @returns {string}
 */
/**
 * 进阶版：自动处理单双栏混合排版 + 首字下沉修复
 */
static getPageContent(pageNo, doc = this.currentDocController.document) {
    if (!doc) return "";
    if (pageNo === undefined) pageNo = this.currentDocController.currPageNo;
    if (pageNo < 1) pageNo = 1;

    // 1. 获取原始数据
    const lines = this.extractRawLines(pageNo, doc);
    if (!lines.length) return "";

    // 2. 版面分析
    const layout = this.analyzeLayout(lines);

    // 3. 预处理：处理首字下沉 (Drop Cap)
    // 必须在排序前处理，因为DropCap的Y坐标(基线)通常比它所属的第一行要低
    const processedLines = this.mergeDropCaps(lines);

    // 4. 全局排序：从上到下 (Top to Bottom)
    // 使用 (y + height) 即顶部坐标进行排序，比基线排序更稳定，特别是混合字号时
    processedLines.sort((a, b) => {
        const aTop = a.y + a.height;
        const bTop = b.y + b.height;
        // 允许 3px 的误差
        if (Math.abs(aTop - bTop) > 3) {
            return bTop - aTop; // 降序，顶部高的在前面
        }
        return a.x - b.x; // 同高度，从左到右
    });

    // 5. 定义通栏判定
    const isCrossColumn = (line) => {
        // 如果页面本身判定为单栏，则所有行都不算“跨栏”（直接按单栏流式处理）
        if (!layout.isTwoColumn) return false;
        
        // 双栏模式下，只有横跨中线的才算通栏（如大标题）
        // 判定：左边界明显在左栏，右边界明显在右栏
        return (line.x < layout.splitX - 20) && (line.right > layout.splitX + 20);
    };

    // 6. 核心段落合并逻辑
    const processChunk = (chunkLines) => {
        if (!chunkLines.length) return [];
        
        // 再次排序确保块内顺序正确 (基于 Top 坐标)
        chunkLines.sort((a, b) => (b.y + b.height) - (a.y + a.height));

        const paragraphs = [];
        let currentPara = "";
        let lastLine = null;

        for (let i = 0; i < chunkLines.length; i++) {
            const curLine = chunkLines[i];
            
            if (!lastLine) {
                currentPara = curLine.text;
                lastLine = curLine;
                continue;
            }

            // --- 智能换段/合并判断 ---
            
            // 1. 计算垂直间距 (Gap)
            // 使用 Top 差值计算更直观
            const lastTop = lastLine.y + lastLine.height;
            const curTop = curLine.y + curLine.height;
            const lineGap = lastTop - curTop - curLine.height; // 近似间距
            
            // 2. 判定条件
            // 间距过大（超过行高 1.5 倍） -> 新段落
            const isGapLarge = lineGap > (Math.max(lastLine.height, curLine.height) * 1.2);
            
            // 缩进判断 (Indentation)
            // 如果当前行 X 比上一行明显靠右 (> font size)，可能是新段落
            // 注意：这里简单比较 x，如果是双栏，需要比较相对于栏目起点的 x
            let isIndented = false;
            const colStartX = (!layout.isTwoColumn || curLine.x < layout.splitX) 
                              ? layout.standardLeftX : layout.standardRightX;
            
            // 如果这一行比标准左边距缩进了 > 15px
            if (curLine.x - (layout.isTwoColumn ? colStartX : layout.standardLeftX || 39) > 15) {
                isIndented = true;
            }

            // 标点符号判断
            const endsWithHyphen = /-$/.test(lastLine.text);
            const endsWithPunct = /[。.?!？！]$/.test(lastLine.text);

            // 3. 决策：合并还是新段
            if (isGapLarge || isIndented) {
                paragraphs.push(currentPara);
                currentPara = curLine.text;
            } else {
                // 合并
                let separator = " ";
                if (endsWithHyphen) {
                    // 连字符处理：去掉 -，不加空格
                    currentPara = currentPara.slice(0, -1);
                    separator = ""; 
                } else if (/[a-zA-Z0-9]$/.test(lastLine.text) && /^[a-zA-Z0-9]/.test(curLine.text)) {
                    // 英文单词间补空格
                    separator = " ";
                } else {
                    // 中文等其他情况可能不需要空格
                    separator = ""; 
                    if(/[a-zA-Z]/.test(lastLine.text) || /[a-zA-Z]/.test(curLine.text)) separator = " ";
                }
                currentPara += separator + curLine.text;
            }
            lastLine = curLine;
        }
        if (currentPara) paragraphs.push(currentPara);
        return paragraphs;
    };

    const finalResult = [];
    let buffer = [];

    const flushBuffer = () => {
        if (buffer.length === 0) return;

        // --- 关键修复：单栏模式下直接处理，不分左右 ---
        if (!layout.isTwoColumn) {
            finalResult.push(...processChunk(buffer));
        } else {
            // 双栏模式下才拆分
            const leftCol = [];
            const rightCol = [];
            
            buffer.forEach(l => {
                const mid = (l.x + l.right) / 2;
                if (mid < layout.splitX) leftCol.push(l);
                else rightCol.push(l);
            });

            if (leftCol.length) finalResult.push(...processChunk(leftCol));
            if (rightCol.length) finalResult.push(...processChunk(rightCol));
        }
        buffer = [];
    };

    processedLines.forEach(line => {
        if (isCrossColumn(line)) {
            flushBuffer();
            finalResult.push(line.text); // 通栏通常是标题，直接作为一段
        } else {
            buffer.push(line);
        }
    });
    flushBuffer();

    return finalResult
        .map(p => p.replace(/\s+/g, ' ').trim())
        .join("\n\n");
}

/**
 * 辅助函数：合并首字下沉 (Drop Caps)
 * 原理：找到特别高大的单个字符，将其文本拼接到其右侧第一行的开头，并从原列表中移除该对象
 */
static mergeDropCaps(lines) {
    if (lines.length < 2) return lines;

    // 计算中位数行高，用于判断什么是“特别大”的字
    const heights = lines.map(l => l.height).sort((a, b) => a - b);
    const medianHeight = heights[Math.floor(heights.length / 2)];
    
    // 阈值：高度大于中位数 2 倍，且文本长度为 1 (或很短)
    const dropCaps = lines.filter(l => l.height > medianHeight * 2.5 && l.text.length < 3);
    
    if (dropCaps.length === 0) return lines;

    const remainingLines = lines.filter(l => !dropCaps.includes(l));

    dropCaps.forEach(cap => {
        // 寻找这个首字下沉属于哪一行
        // 条件：在 DropCap 的右侧，且垂直方向上有重叠（通常是 DropCap 的顶部对应正文第一行）
        
        const capTop = cap.y + cap.height;
        const capBottom = cap.y;

        // 找到候选者
        let targetLine = null;
        let minXDist = 9999;

        remainingLines.forEach(line => {
            const lineTop = line.y + line.height;
            // 判定垂直重叠：行的顶部 在 DropCap 的 Top 和 Bottom 之间
            // 或者行的 Y 坐标接近 DropCap 的顶部（容错 20px）
            const isVerticallyAligned = (lineTop <= capTop + 10) && (line.y >= capBottom);
            
            if (isVerticallyAligned) {
                // 判定水平位置：必须在 Cap 右侧
                if (line.x > cap.x) {
                    const dist = line.x - cap.right;
                    if (dist < minXDist) {
                        minXDist = dist;
                        targetLine = line;
                    }
                }
            }
        });

        if (targetLine) {
            // 合并文本
            targetLine.text = cap.text + targetLine.text;
            // 调整 targetLine 的几何属性（可选，向左扩展以包含 DropCap，便于后续缩进计算）
            targetLine.x = cap.x; 
        } else {
            // 如果没找到合并目标（罕见），还是把它放回去，免得丢字
            remainingLines.push(cap);
        }
    });

    return remainingLines;
}

static getImageSize(imageData){
  let image = UIImage.imageWithData(imageData)
  return image.size
}

static isEmptyImage(imageData){
  let size = this.getImageSize(imageData)
  if (size.width === 1 && size.height === 1) {
    return true
  }
  return false  
}
/**
 * 
 * @param {MNNote} note 
 * @returns {boolean}
 */
static isBlankNote(note){//指有图片摘录但图片分辨率为1x1的空白图片
  if (note.excerptPic) {
    let imageData = MNUtil.getMediaByHash(note.excerptPic.paint)
    if (this.isEmptyImage(imageData)) {
      return true
    }
  }
  return false
}


  /**
   * 
   * @param {MNNote} note 
   * @returns {boolean}
   */
  static isPureImageNote(note){
    if (note.noteTitle) {
      return false
    }
    if (note.comments.length) {
      return false
    }
    if (note.excerptPic) {
      if (note.textFirst) {
        if (note.excerptTextMarkdown) {
          return this.isPureMNImages(note.excerptText)
        }
        return false
      }
      if ("video" in note.excerptPic) {
        return false
      }
      let imageData = MNUtil.getMediaByHash(note.excerptPic.paint)
      let image = UIImage.imageWithData(imageData)
      if (image.size.width === 1 && image.size.height === 1) {
        return false
      }
      return true
    }
    return false
  }
  /**
   * 解压zip文件
   * @param {string|NSData} zipPath 可以直接传入zip文件路径，也可以传入NSData对象
   * @param {string} destination 解压到的目标文件夹路径，会自动检测是否存在，不存在则创建
   * @returns {boolean} 解压成功返回true，否则返回false
   */
  static unzip(zipPath,destination) {
  try {
    this.createFolderDev(destination)
    let realPath = ""
    if (typeof zipPath === "string") {
      realPath = zipPath
    }else{
      realPath = MNUtil.cacheFolder+"/zip_"+MNUtil.UUID()+".zip"
      zipPath.writeToFileAtomically(realPath,false)
    }
    let success = ZipArchive.unzipFileAtPathToDestination(realPath,destination)
    if (success) {
      return true
    }
    return false
      
  } catch (error) {
    this.addErrorLog(error, "unzip")
    return false
  }
  }
  static getLogObject(log,defaultLevel="INFO",defaultSource="Default"){
    let type = typeof log
    if (type === "boolean") {
      log = {
        message:log.toString(),
        level:defaultLevel,
        source:defaultSource,
        timestamp:Date.now()
      }
      return log
    }

    if (type == "string" || type == "number") {
      log = {
        message:log,
        level:defaultLevel,
        source:defaultSource,
        timestamp:Date.now()
      }
      return log
    }
    if (type === "object") {
      if (Array.isArray(log)) {
        return {
          message: "Array of "+log.length+" items",
          detail: JSON.stringify(log,null,2),
          level: defaultLevel,
          source: defaultSource,
          timestamp: Date.now()
        }
      }
    }
    if (!("message" in log)) {
      log.message = "See detail";
    }
    if ("level" in log) {
      log.level = log.level.toUpperCase();
    }else{
      log.level = defaultLevel;
    }
    if (!("source" in log)) {
      log.source = defaultSource;
    }
    if (!("timestamp" in log)) {
      log.timestamp = Date.now();
    }
    if ("detail" in log) {
      if (typeof log.detail == "object") {
        log.detail = JSON.stringify(log.detail,null,2)
      }
    }else{
      let keys = Object.keys(log)
      if (keys.length !== 0) {
        let keysRemain = keys.filter(key => key != "timestamp" && key != "source" && key != "level" && key != "message")
        if (keysRemain.length) {
          let detail = {}
          keysRemain.forEach(key => detail[key] = log[key])
          log.detail = JSON.stringify(detail,null,2)
        }
      }
    }
    return log
  }
  static log(message,detail = undefined){
    if (typeof MNLog === "undefined") {
      let logObject = this.getLogObject(message)
      switch (logObject.level) {
        case "INFO":
          console.log(logObject.message,logObject.detail)
          break;
        case "WARN":
          console.warn(logObject.message,logObject.detail)
          break;
        case "ERROR":
          console.error(logObject.message,logObject.detail)
          break;
        case "DEBUG":
          console.debug(logObject.message,logObject.detail)
          break;
        default:
          break;
      }
      return
    }
    MNLog.log(message,detail)
  }
  static installAddonFromLocalFile(filePath){
    let beginDate = Date.now()
    let tempFolder = filePath.replace(/\.mnaddon$/,"")
    let success = ZipArchive.unzipFileAtPathToDestination(filePath,tempFolder)
    if (!success) {
      return {success:false,error:"Unzip file failed!"}
    }
    let addonConfig = this.readJSON(tempFolder+"/mnaddon.json")
    let addonId = addonConfig.addonid
    let addonPath = subscriptionUtils.extensionPath+"/"+addonId
    success = this.moveFolderToCacheFolder(addonPath)
    if (!success) {
      return {success:false,error:"Remove original folder failed!"}
    }
    success = this.moveFile(tempFolder, addonPath)
    if (!success) {
      return {success:false,error:"Move file failed!"}
    }
    let endDate = Date.now()
    this.log("installAddonFromLocalFile.time: "+(endDate-beginDate)+"ms",{filePath:filePath,tempFolder:tempFolder,addonId:addonId,addonPath:addonPath})
    return {success:true,addonId:addonId}
  }
static async processData(data,options = {}){
try {

  let targetPath = options.targetPath
  if (!targetPath) {
    return {success:false,error:"targetPath is required"}
  }
  let folder = options.folder??this.cacheFolder+"/temp_"+Date.now()
  data.writeToFileAtomically(targetPath,false)
  let fileType = options.fileType
  let notebookId = options.notebookId??this.currentNotebookId
  switch (fileType) {
    case "mnaddon":
          let res = this.installAddonFromLocalFile(targetPath)
          if (res.success) {
            this.stopHUD()
            return {success:true}
            // self.sideBarNotification("安装完成，请手动重启MN")
          }else{
            this.waitHUD(Locale.at("installFailed"))
            subscriptionUtils.log("installAddonFromLocalFile failed",res)
            return {success:false,error:"Install addon from local file failed!"}
          }
      break;
    case "document":
      let fileName = this.getFileName(targetPath)
      let md5 = this.importDocument(targetPath)
      if (this.currentNotebookId) {
        let confirm = await this.confirm("MN Utils","Open document?\n\n是否打开该文档？\n"+fileName)
        if (confirm) {
          // this.copy(this.currentNotebookId)
          this.openDoc(md5,this.currentNotebookId)
        }
      }
      return {success:true}
    case "notebook":
      if (targetPath.endsWith(".marginpkg") || targetPath.endsWith(".marginnotes")) {
        this.importNotebook(targetPath,folder,notebookId)
      }
      return {success:true}
  }
  return {success:false,error:"Invalid file type: "+fileType}
  
} catch (error) {
  this.addErrorLog(error, "processData")
  return {success:false,error:error}
}
}
  /**
   * id为可选,在此仅影响文件名,不影响安装插件,实际的id会从插件的mnaddon.json中读取
   * @param {string} url 
   * @param {string} id 
   * @returns {Promise<{success:boolean,error:string}>}
   */
  static async installAddonFromURL(url,id){
    try {
      let fileName =  id?(id+"_"+Date.now()+".mnaddon"):("temp_"+Date.now()+".mnaddon")
      let targetPath = this.cacheFolder+"/"+fileName
      if (id) {
        this.waitHUD(Locale.at("downloading")+": "+id)
      }else{
        this.waitHUD(Locale.at("downloading")+"...")
      }
      let res = await MNConnection.fetchDev(url,{
        method: "GET",
        headers:{
          "Cache-Control": "no-cache"
        }
      })
      if (res.ok) {
        let data = res.body
        let options = {
          targetPath:targetPath,
          fileType: "mnaddon",
          addonId: id,
          folder: this.cacheFolder,
          notebookId: undefined,
          addonURL: url,
          fileName: fileName
        }
        let result = await this.processData(data,options)
        return result
      }
      
    } catch (error) {
      this.addErrorLog(error, "installAddonFromURL")
      return {success:false,error:error}
    }
  }
}

/**
 * 类似fetch的Response对象
 */
class Response {
  /**
   * 创建一个模拟的 Response 对象
   * @param {NSData} data - 响应主体内容
   * @param {Object} [init] - 响应初始化选项
   */
  constructor(data = null, init = {}) {
    // 设置响应状态码和状态文本
    this.status = init.status !== undefined ? init.status : 200;
    this.statusText = init.statusText || (this.status >= 200 && this.status < 300 ? 'OK' : '');
    this.statusCodeDescription = MNUtil.getStatusCodeDescription(this.status) || '';
    
    // 初始化标头，使用 Headers 对象管理
    this.headers = new Headers(init.headers || {});
    
    // 设置响应主体
    if (data && !MNUtil.isNSNull(data)) {
      //空响应时传入的data可能为NSNull而非null
      this.body = data
    }
    
    // 设置响应类型标识
    this.type = init.type || 'default';
    this.url = init.url || '';
    this.redirected = init.redirected || false;
    this.ok = this.status >= 200 && this.status < 300;
    if (init.error) {
      this.error = init.error
    }
    
    // 缓存读取操作的 Promise
    this._bodyUsed = false;
    this._readPromises = new Map();
  }
  /**
   * 
   * @param {NSHTTPURLResponse} res 
   * @param {NSData} data 
   * @param {NSError} err 
   * @returns {Response}
   */
  static new(res,data,err,url,headers){
    let init = {}
    if (err && !MNUtil.isNSNull(err) && err.localizedDescription) {
      init.error = err.localizedDescription
    }
    if (headers) {
      init.headers = headers
    }
    if (!res || MNUtil.isNSNull(res)) {
      //API似乎存在bug，有时候res是null，这时候status为0，但是不代表无响应
      if (init.error) {
        init.status = 0
      }else{
        //如果没报错，则认为是200
        init.status = 200
      }
    }else{
      init.status = res.statusCode()
    }
    if (url) {
      init.url = url
    }
    return new Response(data,init)
  }
  /**
   * 响应内容复制到剪贴板，方便查看
   */
  copy(){
    let json = this.asJSONObject()
    MNUtil.copy(json)
  }
  asJSONObject(){
    try {

    let res = {
      status:this.status,
      statusText:this.statusText,
      statusCodeDescription:this.statusCodeDescription,
      headers:this.headers,
      type:this.type,
      url:this.url,
      error:this.error
    }
    if (this.body) {
      res.text = this.text()
      res.json = this.json()
      res.bodySize = this.body.length()
    }
    return res
      
    } catch (error) {
      MNUtil.addErrorLog(error, "Response.asJSONObject")
      return undefined
    }
  }

  /**
   * 解析响应主体为 Uint8Array
   * @param {BodyInit|null} body - 原始响应主体
   * @returns {Uint8Array|null} 解析后的二进制数组
   */
  _parseBody(body) {
    if (!body) return null;
    
    if (body instanceof Uint8Array) {
      return body;
    }
    
    // 文本类型转换为 UTF-8 字节
    if (typeof body === 'string') {
      const encoder = new TextEncoder();
      return encoder.encode(body);
    }
    
    // FormData 处理（简化版）
    if (body instanceof FormData) {
      const entries = Array.from(body.entries())
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join('&');
      const encoder = new TextEncoder();
      return encoder.encode(entries);
    }
    
    throw new Error('Unsupported body type');
  }

  /**
   * 标记响应主体已被使用
   */
  _setBodyUsed() {
    //暂不启用
    return
    if (this._bodyUsed) {
      throw new TypeError('Body has already been consumed');
    }
    this._bodyUsed = true;
  }

  /**
   * 将响应主体转换为 ArrayBuffer
   * @returns {Promise<ArrayBuffer>}
   */
  arrayBuffer() {
    if (!this.body) {
      return Promise.resolve(new ArrayBuffer(0));
    }
    
    if (this._readPromises.has('arrayBuffer')) {
      return this._readPromises.get('arrayBuffer');
    }
    
    this._setBodyUsed();
    const promise = Promise.resolve(this.body.buffer.slice(
      this.body.byteOffset,
      this.body.byteOffset + this.body.byteLength
    ));
    
    this._readPromises.set('arrayBuffer', promise);
    return promise;
  }

  /**
   * 将响应主体转换为 Blob
   * @returns {Promise<Blob>}
   */
  blob() {
    return this.arrayBuffer().then(buffer => {
      const type = this.headers.get('content-type') || '';
      return new Blob([buffer], { type });
    });
  }
  get hasJSONResult(){
    let jsonResult = this.json()
    if (jsonResult && Object.keys(jsonResult).length > 0) {
      return true
    }
    return false
  }

  /**
   * 将响应主体转换为 JSON
   * 不包括statusCode等信息
   * @returns {Object|undefined}
   */
  json() {
    if (!this.body) {
      return Promise.resolve(undefined);
    }
    try {
    if (this.jsonResult) {
      // 避免重复解析
      return this.jsonResult
    }

    let result = NSJSONSerialization.JSONObjectWithDataOptions(
      this.body,
      1<<0
    )
    let validJson = NSJSONSerialization.isValidJSONObject(result)
    if (validJson) {
      this.jsonResult = result
      return result;
    }
    this._setBodyUsed();
    return new SyntaxError('Invalid JSON');
      
    } catch (error) {
      MNUtil.addErrorLog(error, "Response.json")
      return new SyntaxError('Invalid JSON');
    }
  }

  /**
   * 将响应主体转换为文本
   * @returns {string}
   */
  text() {
    if (!this.body) {
      return Promise.resolve('');
    }
    if (this.textResult) {
      // 避免重复解析
      return this.textResult
    }
    let text = MNUtil.dataToString(this.body)
    this.textResult = text
    this._setBodyUsed();
    return text
  }

  /**
   * 将响应主体转换为 FormData
   * @returns {Promise<FormData>}
   */
  formData() {
    return this.text().then(text => {
      const formData = new FormData();
      text.split('&').forEach(pair => {
        if (!pair) return;
        const [key, value] = pair.split('=').map(decodeURIComponent);
        formData.append(key, value);
      });
      return formData;
    });
  }

  /**
   * 克隆响应对象
   * @returns {Response}
   */
  clone() {
    if (this._bodyUsed) {
      throw new TypeError('Cannot clone a response that has been consumed');
    }
    
    // 创建新实例并复制属性
    const clonedBody = this.body ? new Uint8Array(this.body) : null;
    return new Response(clonedBody, {
      status: this.status,
      statusText: this.statusText,
      headers: new Headers(this.headers),
      type: this.type,
      url: this.url,
      redirected: this.redirected
    });
  }

  /**
   * 创建一个重定向响应
   * @param {string} url - 重定向目标 URL
   * @param {number} [status=302] - 重定向状态码
   * @returns {Response}
   */
  static redirect(url, status = 302) {
    if (![301, 302, 303, 307, 308].includes(status)) {
      throw new RangeError('Invalid status code');
    }
    
    return new Response(null, {
      status,
      headers: { Location: url }
    });
  }

  /**
   * 创建一个错误响应
   * @returns {Response}
   */
  static error() {
    return new Response(null, {
      status: 0,
      type: 'error'
    });
  }
}

// 用于管理响应头的类
class Headers {
  /**
   * 创建一个 Headers 实例
   * @param {HeadersInit} [init] - 初始头信息
   */
  constructor(init = {}) {
    this._headers = new Map();
    
    // 从不同格式初始化头信息
    if (init instanceof Headers) {
      init.forEach((value, key) => this.append(key, value));
    } else if (Array.isArray(init)) {
      init.forEach(([key, value]) => this.append(key, value));
    } else if (typeof init === 'object') {
      Object.entries(init).forEach(([key, value]) => this.append(key, value));
    }
  }

  /**
   * 添加头信息（不覆盖现有同名头）
   * @param {string} name - 头名称
   * @param {string} value - 头值
   */
  append(name, value) {
    const key = name.toLowerCase();
    const current = this._headers.get(key);
    this._headers.set(key, current ? `${current}, ${value}` : value.toString());
  }

  /**
   * 删除指定头信息
   * @param {string} name - 头名称
   */
  delete(name) {
    this._headers.delete(name.toLowerCase());
  }

  /**
   * 获取指定头信息
   * @param {string} name - 头名称
   * @returns {string|null}
   */
  get(name) {
    return this._headers.get(name.toLowerCase()) || null;
  }

  /**
   * 检查是否包含指定头信息
   * @param {string} name - 头名称
   * @returns {boolean}
   */
  has(name) {
    return this._headers.has(name.toLowerCase());
  }

  /**
   * 设置指定头信息（覆盖现有同名头）
   * @param {string} name - 头名称
   * @param {string} value - 头值
   */
  set(name, value) {
    this._headers.set(name.toLowerCase(), value.toString());
  }

  /**
   * 迭代所有头信息
   * @param {function} callback - 回调函数
   * @param {any} [thisArg] - 回调函数的 this 上下文
   */
  forEach(callback, thisArg) {
    this._headers.forEach((value, key) => callback.call(thisArg, value, key, this));
  }

  /**
   * 获取所有头名称迭代器
   * @returns {IterableIterator<string>}
   */
  keys() {
    return this._headers.keys();
  }

  /**
   * 获取所有头值迭代器
   * @returns {IterableIterator<string>}
   */
  values() {
    return this._headers.values();
  }

  /**
   * 获取所有头键值对迭代器
   * @returns {IterableIterator<[string, string]>}
   */
  entries() {
    return this._headers.entries();
  }

  [Symbol.iterator]() {
    return this.entries();
  }
}
class MNWebview {
  /**
   * 
   * @param {CGRect} frame 
   */
  constructor(frame) {
    this.webview = new UIWebView(frame);
  }
  /**
   * 
   * @param {string|UIColor} color 
   */
  set backgroundColor(color) {
    if (typeof color === 'string') {
      this.webview.backgroundColor = MNUtil.hexColor(color)
    } else {
      this.webview.backgroundColor = color
    }
  }
  /**
   *
   * @returns {CALayer}
   */
  get layer(){
    return this.webview.layer
  }

  /**
   * 
   * @param {string|UIColor} color 
   */
  set borderColor(color){
    if (typeof color === 'string') {
      this.webview.layer.borderColor = MNUtil.hexColor(color)
    } else {
      this.webview.layer.borderColor = color
    }
  }
  /**
   * 
   * @param {number} width 
   */
  set borderWidth(width){
    this.webview.layer.borderWidth = width
  }
  /**
   *
   * @returns {number}
   */
  get borderWidth(){
    return this.webview.layer.borderWidth
  }
  set cornerRadius(radius){
    this.webview.layer.cornerRadius = radius
  }
  /**
   *
   * @returns {number}
   */
  get cornerRadius(){
    return this.webview.layer.cornerRadius
  }
  /**
   *
   * @param {boolean} masksToBounds 
   */
  set masksToBounds(masksToBounds){
    this.webview.layer.masksToBounds = masksToBounds
  }
  /**
   *
   * @returns {boolean}
   */
  get masksToBounds(){
    return this.webview.layer.masksToBounds
  }
  /**
   *
   * @returns {boolean}
   */
  get hidden(){
    return this.webview.hidden
  }
  /**
   *
   * @param {boolean} hidden 
   */
  set hidden(hidden){
    this.webview.hidden = hidden
  }
  /**
   * 
   * @param {boolean} scalesPageToFit 
   */
  set scalesPageToFit(scalesPageToFit) {
    this.webview.scalesPageToFit = scalesPageToFit
  }
  /**
   * 
   * @param {number} autoresizingMask 
   */
  set autoresizingMask(autoresizingMask) {
    this.webview.autoresizingMask = autoresizingMask
  }
  /**
   * 
   * @param {CGRect} frame 
   */
  set frame(frame) {
    this.webview.frame = frame
  }
  /**
   *
   * @returns {CGRect}
   */
  get frame(){
    return this.webview.frame
  }

  /**
   *
   * @param {number} height 
   */
  set height(height){
    let frame = this.webview.frame
    frame.height = height
    this.webview.frame = frame
  }
  /**
   *
   * @returns {number}
   */
  get height(){
    return this.webview.frame.height
  }
  /**
   *
   * @param {number} width 
   */
  set width(width){
    let frame = this.webview.frame
    frame.width = width
    this.webview.frame = frame
  }
  /**
   *
   * @returns {number}
   */
  get width(){
    return this.webview.frame.width
  }
  /**
   *
   * @param {{width:number,height:number}} size 
   */
  set size(size){
    let frame = this.webview.frame
    frame.width = size.width
    frame.height = size.height
    this.webview.frame = frame
  }
  /**
   *
   * @returns {{width:number,height:number}}
   */
  get size(){
    return {width:this.webview.frame.width,height:this.webview.frame.height}
  }
  /**
   *
   * @param {number} x 
   */
  set x(x){
    let frame = this.webview.frame
    frame.x = x
    this.webview.frame = frame
  }
  /**
   *
   * @returns {number}
   */
  get x(){
    return this.webview.frame.x
  }
  /**
   *
   * @param {number} y 
   */
  set y(y){
    let frame = this.webview.frame
    frame.y = y
    this.webview.frame = frame
  }
  /**
   *
   * @returns {number}
   */
  get y(){
    return this.webview.frame.y
  }

  /**
   * 
   * @param {UIWebViewDelegate} delegate 
   */
  set delegate(delegate) {
    this.webview.delegate = delegate
  }
  /**
   * 
   * @param {UIWebViewDelegate} delegate 
   */
  get delegate(){
    return this.webview.delegate
  }

  /**
   * 
   * @param {boolean} desktop 
   */
  set webMode(desktop){
    this.setWebMode(this.webview,desktop)
  }
  /**
   * 
   * @param {boolean} desktop 
   */
  get webMode(){
    return this.webview.customUserAgent === 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
  }
  set desktop(desktop){
    this.setWebMode(this.webview,desktop)
  }
  /**
   * 
   * @param {boolean} desktop 
   */
  get desktop(){
    return this.webview.customUserAgent === 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
  }
  /**
   * 
   * @param {string} userAgent 
   */
  set customUserAgent(userAgent){
    this.webview.customUserAgent = userAgent
  }
  /**
   * 
   * @param {string} userAgent 
   */
  set UA(userAgent){
    this.webview.customUserAgent = userAgent
  }
  /**
   * 
   * @returns {string}
   */
  get customUserAgent(){
    return this.webview.customUserAgent
  }
  /**
   * 
   * @returns {string}
   */
  get UA(){
    return this.webview.customUserAgent
  }
  get currentURL(){
    return this.webview.request.URL().absoluteString()
  }
  get window(){
    return this.webview.window
  }
  get scrollView(){
    return this.webview.scrollView
  }
  /**
   * 
   * @returns {{x:number,y:number}}
   */
  get contentOffset(){
    return this.webview.scrollView.contentOffset
  }
  /**
   * 
   * @param {{x:number,y:number}} contentOffset 
   */
  set contentOffset(contentOffset){
    this.webview.scrollView.contentOffset = contentOffset
  }
  /**
   * 
   * @returns {Promise<any>}
   */
  async blur(){
    await MNWebview.blur(this.webview)
  }
/** 
* @description 获取当前网页的信息
* @returns {Promise<{url:string, title:string, hasVideo:boolean, videoTime:number, urlConfig:{url: string, scheme: string, host: string, query: string ,params: any, pathComponents: string[], isBlank: boolean, fragment: string}}>} 当前网页的信息
*/
async getCurrentWebInfo() {
  if(!this.webview || !this.webview.window) return;

  let encodedInfo = await this.runJavaScript(`function currentWebInfo() {
    let url = window.location.href
    let title = document.title
    let hasVideo = document.getElementsByTagName('video').length > 0
    let info = {url, title, hasVideo}
    if (hasVideo) {
      info.videoTime = document.getElementsByTagName('video')[0].currentTime;
    }
    return encodeURIComponent(JSON.stringify(info))
  }
  currentWebInfo()
  `)
  let info = JSON.parse(decodeURIComponent(encodedInfo))
  info.desktop = this.desktop ?? false
  info.urlConfig = MNUtil.parseURL(info.url)
  return info
};
/**
 * 
 * @returns {Promise<string>}
 */
async getSelectedTextInWebview() {
  let ret = await this.runJavaScript(`
      function getCurrentSelect(){

      let selectionObj = null, rangeObj = null;
      let selectedText = "", selectedHtml = "";

      if(window.getSelection){
        selectionObj = window.getSelection();
        selectedText = selectionObj.toString();
      }
      return selectedText
    };
      getCurrentSelect()
    `)
  return ret
}
/**
 * 
 * @returns {Promise<string>}
 */
async getTextInWebview() {
  let ret = await this.runJavaScript(`
    function getSelectOrWholeText(){

      let selectionObj = null, rangeObj = null;
      let selectedText = "", selectedHtml = "";

      if(window.getSelection){
        selectionObj = window.getSelection();
        selectedText = selectionObj.toString();
        return selectedText === ""?document.body.innerText:selectedText
      }else{
        return document.body.innerText;
      }
    };
    getSelectOrWholeText()
    `)
  return ret
}
async takeSnapshotWithWidth(width){
  return new Promise((resolve, reject) => {
    this.webview.takeSnapshotWithWidth(width,(snapshot)=>{
      resolve(snapshot.pngData())
    })
  })
}
async screenshot(width){
  return new Promise((resolve, reject) => {
    this.webview.takeSnapshotWithWidth(width,(snapshot)=>{
      resolve(snapshot.pngData())
    })
  })
}

endEditing(){
  this.webview.endEditing(true)
}
/**
 * 
 * @param {UIView} view 
 */
  addSubview(view){
    this.webview.addSubview(view)
  }
  removeFromSuperview(){
    this.webview.removeFromSuperview()
  }
  /**
   * 
   * @param {NSURLRequest} request 
   */
  loadRequest(request){
    this.webview.loadRequest(request)
  }
  /**
   * 
   * @param {string} url 
   * @param {boolean} desktop 
   */
  loadURL(url,desktop){
    MNWebview.loadRequest(this.webview,url,desktop)
  }
  /**
   * 
   * @param {string} path 
   */
  loadPDF(path){
    MNWebview.loadPDF(this.webview,path)
  }
  /**
   * 
   * @param {string} file 
   * @param {string} baseURL 
   */
  loadFile(file,baseURL){
    this.webview.loadFileURLAllowingReadAccessToURL(
      NSURL.fileURLWithPath(file),
      NSURL.fileURLWithPath(baseURL)
    )
  }
  goBack(){
    this.webview.goBack()
  }
  goForward(){
    this.webview.goForward()
  }
  /**
   * 
   * @returns {boolean}
   */
  get canGoForward(){
    return this.webview.canGoForward()
  }
  reload(){
    this.webview.reload()
  }
  stopLoading(){
    this.webview.stopLoading()
  }
  evaluateJavaScript(script){
    this.webview.evaluateJavaScript(script)
  }
  canGoBack(){
    return this.webview.canGoBack()
  }
  /**
   * 
   * @param {string} html
   * @param {string} baseURL 
   */
  loadHTML(html,baseURL){
    let data = NSData.dataWithStringEncoding(html,4)
    this.webview.loadDataMIMETypeTextEncodingNameBaseURL(data,"text/html","UTF-8",MNUtil.genNSURL(baseURL+"/"))
  }
  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} fileURL
   * @param {string} baseURL 
   */
  static loadFile(webview,file,baseURL){
    webview.loadFileURLAllowingReadAccessToURL(
      NSURL.fileURLWithPath(file),
      NSURL.fileURLWithPath(baseURL)
    )
  }
  /**
   * 
   * @param {string} html
   * @param {string} baseURL 
   */
  static loadHTML(webview,html,baseURL){
    let data = NSData.dataWithStringEncoding(html,4)
    webview.loadDataMIMETypeTextEncodingNameBaseURL(data,"text/html","UTF-8",MNUtil.genNSURL(baseURL+"/"))
  }

  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} path 
   */
  static loadPDF(webview,path){
    let pdfData = MNUtil.getFile(path)
    webview.loadDataMIMETypeTextEncodingNameBaseURL(pdfData,"application/pdf","UTF-8",undefined)
  }
  /**
   * Loads a URL request into a web view.
   * 
   * This method loads the specified URL into the provided web view. It creates an NSURLRequest object
   * from the given URL and then instructs the web view to load this request.
   * 
   * @param {UIWebView} webview - The web view into which the URL should be loaded.
   * @param {string} url - The URL to be loaded into the web view.
   */
  static loadRequest(webview,url,desktop){
    if (desktop !== undefined) {
      if (desktop) {
        webview.customUserAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
      }else{
        webview.customUserAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'
      }
    }
    webview.loadRequest(NSURLRequest.requestWithURL(NSURL.URLWithString(url)));
  }
  /**
   * 
   * @param {string} script 
   * @returns {Promise<any>}
   */
  async runJavaScript(script){
    return await MNWebview.runJavaScript(this.webview,script)
  }
  static isNSNull(obj){
    return (obj === NSNull.new())
  }
  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} script 
   * @returns 
   */
  static async runJavaScript(webview,script) {
    // if(!this.webviewResponse || !this.webviewResponse.window)return;
    return new Promise((resolve, reject) => {
      try {
        if (webview) {
          // MNUtil.copy(webview)
          webview.evaluateJavaScript(script,(result) => {
            if (this.isNSNull(result)) {
              resolve(undefined)
            }
            resolve(result)
          });
        }else{
          resolve(undefined)
        }
      } catch (error) {
        MNUtil.addErrorLog(error, "MNWebview.runJavaScript")
        resolve(undefined)
      }
    })
  };
  /**
   * 
   * @param {UIWebView} webview 
   */
  static async blur(webview){
    await this.runJavaScript(webview,`function removeFocus() {
    // 获取当前具有焦点的元素
    const focusedElement = document.activeElement;
    // 如果当前焦点元素存在，移除焦点
    if (focusedElement) {
        focusedElement.blur();
    }
}
removeFocus()`)
    webview.endEditing(true)
  }
  static setWebMode(webview,desktop){
    if (desktop !== undefined) {
      if (desktop) {
        webview.customUserAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
      }else{
        webview.customUserAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'
      }
    }
  }
}
class MNConnection{
  static IPCache = undefined
  static addErrorLog(error,source,info){
    MNUtil.showHUD("Connection Error ("+source+"): "+error)
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
    MNUtil.copyJSON(MNUtil.errorLog)
    if (typeof MNUtil.log !== undefined) {
      MNUtil.log({
        source:"Connection",
        message:source,
        level:"ERROR",
        detail:JSON.stringify(tem,null,2)
      })
    }
  }
  static genURL(url) {
    return NSURL.URLWithString(url)
  }
  // static requestWithURL(url){
  //   return NSURLRequest.requestWithURL(NSURL.URLWithString(url))
  // }
  /**
   * 
   * @param {string} url 
   * @returns {NSMutableURLRequest} 
   */
  static requestWithURL(url){
    return NSMutableURLRequest.requestWithURL(NSURL.URLWithString(url))
  }
  /**
   * Loads a URL request into a web view.
   * 
   * This method loads the specified URL into the provided web view. It creates an NSURLRequest object
   * from the given URL and then instructs the web view to load this request.
   * 
   * @param {UIWebView} webview - The web view into which the URL should be loaded.
   * @param {string} url - The URL to be loaded into the web view.
   */
  static loadRequest(webview,url,desktop){
    if (desktop !== undefined) {
      if (desktop) {
        webview.customUserAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
      }else{
        webview.customUserAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'
      }
    }
    webview.loadRequest(NSURLRequest.requestWithURL(NSURL.URLWithString(url)));
  }
  static setWebMode(webview,desktop){
    if (desktop !== undefined) {
      if (desktop) {
        webview.customUserAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
      }else{
        webview.customUserAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'
      }
    }
  }
  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} fileURL
   * @param {string} baseURL 
   */
  static loadFile(webview,file,baseURL){
    webview.loadFileURLAllowingReadAccessToURL(
      NSURL.fileURLWithPath(file),
      NSURL.fileURLWithPath(baseURL)
    )
  }
  static loadPDF(webview,path){
    let pdfData = MNUtil.getFile(path)
    webview.loadDataMIMETypeTextEncodingNameBaseURL(pdfData,"application/pdf","UTF-8",undefined)
  }
  /**
   * 与loadFile类似，但是file是相对于folder的，也就是相对路径，只有folder需要填绝对路径
   * @param {UIWebView} webview 
   * @param {string} fileURL
   * @param {string} folder 
   */
  static loadFileAtFolder(webview,file,folder){
    if (!MNUtil.isfileExists(folder)) {
      this.addErrorLog(new Error("Folder not found: "+folder), "loadFileAtFolder")
      return
    }
    let fileURL = NSURL.fileURLWithPath(folder+"/"+file)
    webview.loadFileURLAllowingReadAccessToURL(
      fileURL,
      NSURL.fileURLWithPath(folder)
    )
  }
  /**
   * 
   * @param {UIWebView} webview 
   * @param {string} html
   * @param {string} baseURL 
   */
  static loadHTML(webview,html,baseURL){
    let data = NSData.dataWithStringEncoding(html,4)
    webview.loadDataMIMETypeTextEncodingNameBaseURL(data,"text/html","UTF-8",MNUtil.genNSURL(baseURL+"/"))
  }
  /**
   * Initializes an HTTP request with the specified URL and options.
   * 
   * This method creates an NSMutableURLRequest object with the given URL and sets the HTTP method, timeout interval, and headers.
   * It also handles query parameters, request body, form data, and JSON payloads based on the provided options.
   * 
   * @param {string} url - The URL for the HTTP request.
   * @param {Object} options - The options for the HTTP request.
   * @param {string} [options.method="GET"] - The HTTP method (e.g., "GET", "POST").
   * @param {number} [options.timeout=10] - The timeout interval for the request in seconds.
   * @param {Object} [options.headers] - Additional headers to include in the request.
   * @param {Object} [options.search] - Query parameters to append to the URL.
   * @param {string} [options.body] - The request body as a string.
   * @param {Object} [options.form] - Form data to include in the request body.
   * @param {Object} [options.json] - JSON data to include in the request body.
   * @returns {NSMutableURLRequest} The initialized NSMutableURLRequest object.
   */
  static initRequest(url,options) {
    const request = this.requestWithURL(url)
    let method = options.method ?? "GET"
    request.setHTTPMethod(method)
    request.setTimeoutInterval(options.timeout ?? 10)
    const headers = {
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Safari/605.1.15",
      Accept: "application/json"
    }
    if (method !== "GET") {
      headers["Content-Type"] = "application/json"
    }
    // let newHearders = {
    //   ...headers,
    //   ...(options.headers ?? {})
    // }
    // MNUtil.copy(newHearders)
    request.setAllHTTPHeaderFields({
      ...headers,
      ...(options.headers ?? {})
    })
    if (options.search) {
      request.setURL(
        this.genNSURL(
          `${url.trim()}?${Object.entries(options.search).reduce((acc, cur) => {
            const [key, value] = cur
            return `${acc ? acc + "&" : ""}${key}=${encodeURIComponent(value)}`
          }, "")}`
        )
      )
    } else if (options.body) {
      if (typeof options.body === "string") {
        request.setHTTPBody(NSData.dataWithStringEncoding(options.body, 4))
      }else{
        request.setHTTPBody(options.body)
      }
    } else if (options.form) {
      request.setHTTPBody(
        NSData.dataWithStringEncoding(
          Object.entries(options.form).reduce((acc, cur) => {
            const [key, value] = cur
            return `${acc ? acc + "&" : ""}${key}=${encodeURIComponent(value)}`
          }, ""),
          4
        )
      )
    } else if (options.json) {
      request.setHTTPBody(
        NSJSONSerialization.dataWithJSONObjectOptions(
          options.json,
          1
        )
      )
    }
    return request
  }
  /**
   * Sends an HTTP request asynchronously and returns the response data.
   * 
   * This method sends the specified HTTP request asynchronously using NSURLConnection. It returns a promise that resolves with the response data if the request is successful,
   * or with an error object if the request fails. The error object includes details such as the status code and error message.
   * 
   * @param {NSMutableURLRequest} request - The HTTP request to be sent.
   * @returns {Promise<Object>} A promise that resolves with the response data or an error object.
   */
  static async sendRequest(request){
    const queue = NSOperationQueue.mainQueue()
    return new Promise((resolve, reject) => {
      NSURLConnection.sendAsynchronousRequestQueueCompletionHandler(
        request,
        queue,
        (res, data, err) => {
        try {
        if (MNUtil.isNSNull(res)) {
          if (err.localizedDescription){
            let error = {error:err.localizedDescription}
            resolve(error)
            return
          }
          resolve({error:"Response is null"})
          return
        }
        // MNUtil.showHUD("123")

          let result = NSJSONSerialization.JSONObjectWithDataOptions(
            data,
            1<<0
          )
          let validJson = result && NSJSONSerialization.isValidJSONObject(result)
          if (err.localizedDescription){
            MNUtil.showHUD(err.localizedDescription)
            let error = {error:err.localizedDescription}
            if (validJson) {
              error.data = result
            }
            resolve(error)
          }
        // MNUtil.showHUD("456")

          if (res.statusCode() >= 400) {
            let error = {statusCode:res.statusCode()}
            if (validJson) {
              error.data = result
            }
            resolve(error)
          }
        // MNUtil.showHUD("789"+typeof data)

          if (validJson){
            resolve(result)
          }else{
            resolve(data)
          }
        } catch (error) {
        // MNUtil.addErrorLog(error, "sendRequest")
          resolve({error: error.localizedDescription || "Unknown error"})
        }
        }
      )
  })
  }
  /**
   * Sends an HTTP request asynchronously and returns the response data.
   * 
   * This method sends the specified HTTP request asynchronously using NSURLConnection. It returns a promise that resolves with the response data if the request is successful,
   * or with an error object if the request fails. The error object includes details such as the status code and error message.
   * 
   * @param {NSMutableURLRequest} request - The HTTP request to be sent.
   * @returns {Promise<Response>} A promise that resolves with the response data or an error object.
   */
  static async sendRequestDev(request){
    let url = request.URL().absoluteString()
    const queue = NSOperationQueue.mainQueue()
    return new Promise((resolve, reject) => {
      NSURLConnection.sendAsynchronousRequestQueueCompletionHandler(
        request,
        queue,
        /**
         * 
         * @param {NSHTTPURLResponse} res 
         * @param {NSData} data 
         * @param {NSError} err 
         * @returns 
         */
        (res, data, err) => {
          try {
          if (!MNUtil.isNSNull(res)) {
            let headers = res.allHeaderFields()
            resolve(Response.new(res,data,err,url,headers))
          }else{
          resolve(Response.new(res,data,err,url))
          }
            
          } catch (error) {
            this.addErrorLog(error, "sendRequestDev",{url:url})
            resolve(Response.new(res,data,err))
          }
        }
      )
  })
  }
  static sendRequestWithDelegate(request,delegate){
    let connection = NSURLConnection.connectionWithRequestDelegate(request, delegate)
    return connection
  }
  /**
   * Fetches data from a specified URL with optional request options.
   * 
   * This method initializes a request with the provided URL and options, then sends the request asynchronously.
   * It returns a promise that resolves with the response data or an error object if the request fails.
   * 
   * @param {string} url - The URL to fetch data from.
   * @param {Object} [options={}] - Optional request options.
   * @param {string} [options.method="GET"] - The HTTP method to use for the request.
   * @param {number} [options.timeout=10] - The timeout interval for the request in seconds.
   * @param {Object} [options.headers={}] - Additional headers to include in the request.
   * @param {Object} [options.search] - Query parameters to append to the URL.
   * @param {string} [options.body] - The body of the request for POST, PUT, etc.
   * @param {Object} [options.form] - Form data to include in the request body.
   * @param {Object} [options.json] - JSON data to include in the request body.
   * @returns {Promise<Object|Error>} A promise that resolves with the response data or an error object.
   */
  static async fetch (url,options = {}){
    try {

    const request = this.initRequest(url, options)
    // MNUtil.copy(typeof request)
    const res = await this.sendRequest(request)
    // MNUtil.showHUD("Fetch"+(typeof res))
    return res
      
    } catch (error) {
      MNUtil.addErrorLog(error, "fetch")
      return undefined
    }
  }
  /**
   * 对于得到的响应，通过res.ok判断是否成功，通过res.json()获取响应数据
   * fetchDev方法的行为更接近原生fetch，建议使用该方法
   * fetch方法依然保留是为了兼容早期的插件，不建议使用
   * @param {string} url 
   * @param {Object} options 
   * @returns {Promise<Response>} A promise that resolves with the response data or an error object.
   */
  static async fetchDev (url,options = {}){
    try {
    const request = this.initRequest(url, options)
    // MNUtil.copy(typeof request)
    const res = await this.sendRequestDev(request)
    // MNUtil.showHUD("Fetch"+(typeof res))
    return res
      
    } catch (error) {
      MNUtil.addErrorLog(error, "fetch")
      return undefined
    }
  }
  static async fetchHead(url){
    const request = this.initRequest(url, {method: "HEAD"})
    const res = await this.sendRequestDev(request)
    return res
  }
  static async getContentLength(url){
    const res = await this.fetchHead(url)
    if (res.ok) {
      return res.headers.get("Content-Length")
    }
    return undefined
  }
  static async getFileSize(url,unit = "MB"){
    const contentLength = await this.getContentLength(url)
    if (contentLength) {
      if (unit === "MB") {
        return contentLength / 1024 / 1024
      }else if (unit === "KB") {
        return contentLength / 1024
      }else if (unit === "B") {
        return contentLength
      }else{
        return undefined
      }
    }
    return undefined
  }
  static async fetchIPInfo(cache = true){
    try {
      if (cache && this.IPCache) {
        return this.IPCache
      }
      let url = "https://uapis.cn/api/v1/network/myip"
      let headers = {
        "User-Agent": "MarginNote%204/20303 CFNetwork/3826.600.41 Darwin/24.6.0"
      }
      let res = await this.fetchDev(url, {
        headers: headers
      })
      if (res.ok) {
        this.IPCache = res.json()
        return this.IPCache
      }else{
        url = "https://ipapi.co/json/"
        res = await this.fetchDev(url, {
          headers: headers
        })
        if (res.ok) {
          this.IPCache = res.json()
          return this.IPCache
        }else{
          this.addErrorLog(res.asJSONObject(), "fetchIPInfo")
          return undefined
        }
      }
    } catch (error) {
      this.addErrorLog(error, "fetchIPInfo")
      return undefined
    }
  }
  static async isInChina(cache = true){
    let ipInfo = await this.fetchIPInfo(cache)
    if (!ipInfo) {
      return true
    }
    if ("country_name" in ipInfo) {
      return ipInfo.country_name === "China"
    }
    if ("region" in ipInfo) {
      return ipInfo.region.startsWith("中国")
    }
    return true
  }

  /**
   * Encodes a string to Base64.
   * 
   * This method encodes the provided string to a Base64 representation using the CryptoJS library.
   * It first parses the string into a WordArray and then converts this WordArray to a Base64 string.
   * 
   * @param {string} str - The string to be encoded to Base64.
   * @returns {string} The Base64 encoded string.
   */
  static btoa(str) {
      // Encode the string to a WordArray
      const wordArray = CryptoJS.enc.Utf8.parse(str);
      // Convert the WordArray to Base64
      const base64 = CryptoJS.enc.Base64.stringify(wordArray);
      return base64;
  }
  /**
   * Reads a file from a WebDAV server using the provided URL, username, and password.
   * 
   * This method sends a GET request to the specified WebDAV URL with the provided username and password for authentication.
   * It returns a promise that resolves with the response data if the request is successful, or with an error object if the request fails.
   * 
   * @param {string} url - The URL of the file on the WebDAV server.
   * @param {string} username - The username for authentication.
   * @param {string} password - The password for authentication.
   * @returns {Promise<Object>} A promise that resolves with the response data or an error object.
   */
static async readWebDAVFile(url, username, password) {
    const headers = {
      Authorization:'Basic ' + this.btoa(username + ':' + password),
      "Cache-Control": "no-cache"
      };
        const response = await this.fetch(url, {
            method: 'GET',
            headers: headers
        });
    return response
}

  /**
   * Reads a file from a WebDAV server using the provided URL, username, and password.
   * 
   * This method sends a GET request to the specified WebDAV URL with the provided username and password for authentication.
   * It returns a promise that resolves with the response data if the request is successful, or with an error object if the request fails.
   * 
   * @param {string} url - The URL of the file on the WebDAV server.
   * @param {string} username - The username for authentication.
   * @param {string} password - The password for authentication.
   * @returns {NSURLConnection} A promise that resolves with the response data or an error object.
   */
static readWebDAVFileWithDelegate(url, username, password) {
    const headers = {
      Authorization:'Basic ' + this.btoa(username + ':' + password),
      "Cache-Control": "no-cache"
      };
      const request = this.initRequest(url, {
            method: 'GET',
            headers: headers
        })
    return request
}
static requestOfWebDAV(config) {
  const headers = {
    "Cache-Control": "no-cache"
  };
  if (config.authorization) {
    headers.Authorization = config.authorization
  }else{
    headers.Authorization = 'Basic ' + MNUtil.btoa(config.username + ':' + config.password)
  }
  const request = this.initRequest(config.url, {
      method: 'GET',
      headers: headers
  })
  return request
}
static async readJSONFromWebDAV(config) {
  try {

    const request = this.requestOfWebDAV(config)
    const response = await this.sendRequestDev(request)
    try {
      if (!response.ok) {
        return undefined
      }
      let json = response.json()
      return json
    } catch (error) {
      return response
    }
  } catch (error) {
    this.addErrorLog(error, "readJSONFromWebDAV")
    return undefined
  }
}
static async readJSONFromURL(url,headers = {}) {
  try {

    const response = await this.fetchDev(url, {
      headers: headers
    })
    try {
      if (!response.ok) {
        if (response.error){
          if (typeof MNNotification !== "undefined") {
            MNNotification.error("Connection Error",response.error+"\n\n"+url,"MNConnection.readJSONFromURL")
          }else{
            this.addErrorLog(response.error, "readJSONFromURL",{url:url})
          }
        }
        return undefined
      }
      let json = response.json()
      return json
    } catch (error) {
      return response
    }
  } catch (error) {
    this.addErrorLog(error, "readJSONFromURL")
    return undefined
  }
}
static genWebDAVAuthorization(username, password) {
  return 'Basic ' + this.btoa(username + ':' + password)
}
/**
 * Uploads a file to a WebDAV server using the provided URL, username, password, and file content.
 * 
 * This method sends a PUT request to the specified WebDAV URL with the provided username and password for authentication.
 * The file content is included in the request body. It returns a promise that resolves with the response data if the request is successful,
 * or with an error object if the request fails.
 * 
 * @param {string} url - The URL of the file on the WebDAV server.
 * @param {string} username - The username for authentication.
 * @param {string} password - The password for authentication.
 * @param {string} fileContent - The content of the file to be uploaded.
 * @returns {Promise<Object>} A promise that resolves with the response data or an error object.
 */
static async uploadWebDAVFile(url, username, password, fileContent) {
    const headers = {
      Authorization:this.genWebDAVAuthorization(username, password),
      "Content-Type":'application/octet-stream'
    };
    const response = await this.fetch(url, {
        method: 'PUT',
        headers: headers,
        body: fileContent
    });
    return response
}
/**
 * Uploads a file to a WebDAV server using the provided URL, username, password, and file content.
 * 
 * This method sends a PUT request to the specified WebDAV URL with the provided username and password for authentication.
 * The file content is included in the request body. It returns a promise that resolves with the response data if the request is successful,
 * or with an error object if the request fails.
 * 
 * @param {string} url - The URL of the file on the WebDAV server.
 * @param {string} username - The username for authentication.
 * @param {string} password - The password for authentication.
 * @param {NSData} data - The content of the file to be uploaded.
 * @returns {Promise<Object>} A promise that resolves with the response data or an error object.
 */
  static async uploadFileToWebDAV(url, username, password, data) {
      const headers = {
        Authorization:this.genWebDAVAuthorization(username, password),
        "Content-Type":'application/octet-stream'
      };

      try {
          const response = await MNConnection.fetchDev(url, {
              method: 'PUT',
              headers: headers,
              body: data
          });
          return response
      } catch (error) {
        subscriptionUtils.addErrorLog(error, "uploadFileToWebDAV")
        return undefined
      }
}
  static getOnlineImage(url,scale=3){
    MNUtil.showHUD("Downloading image")
    let imageData = NSData.dataWithContentsOfURL(MNUtil.genNSURL(url))
    if (imageData) {
      MNUtil.showHUD("Download success")
      return UIImage.imageWithDataScale(imageData,scale)
    }
    MNUtil.showHUD("Download failed")
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
      if (!isBlankNote) {//实际为文字留白
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
 * Initializes a request for ChatGPT using the provided configuration.
 * 
 * @param {Array} history - An array of messages to be included in the request.
 * @param {string} apikey - The API key for authentication.
 * @param {string} url - The URL endpoint for the API request.
 * @param {string} model - The model to be used for the request.
 * @param {number} temperature - The temperature parameter for the request.
 * @param {Array<number>} funcIndices - An array of function indices to be included in the request.
 * @throws {Error} If the API key is empty or if there is an error during the request initialization.
 */
static initRequestForChatGPT (history,apikey,url,model,temperature,funcIndices=[]) {
  if (apikey.trim() === "") {
    MNUtil.showHUD(model+": No apikey!")
    return
  }
  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer "+apikey,
    Accept: "text/event-stream"
  }
    // copyJSON(headers)
  let body = {
    "model":model,
    "messages":history,
    "stream":true
  }
  // if (model !== "deepseek-reasoner") {
    body.temperature = temperature
    // if (url === "https://api.minimax.chat/v1/text/chatcompletion_v2") {
    //   let tools = chatAITool.getToolsByIndex(funcIndices,true)
    //   if (tools.length) {
    //     body.tools = tools
    //   }
    //   body.max_tokens = 8000
    // }else{
    //   let tools = chatAITool.getToolsByIndex(funcIndices,false)
    //   if (tools.length) {
    //     body.tools = tools
    //     body.tool_choice = "auto"
    //   }
    // }
  const request = MNConnection.initRequest(url, {
      method: "POST",
      headers: headers,
      timeout: 60,
      json: body
    })
  return request
}
/**
 * Initializes a request for ChatGPT using the provided configuration.
 * 
 * @param {Array} history - An array of messages to be included in the request.
 * @param {string} apikey - The API key for authentication.
 * @param {string} url - The URL endpoint for the API request.
 * @param {string} model - The model to be used for the request.
 * @param {number} temperature - The temperature parameter for the request.
 * @param {Array<number>} funcIndices - An array of function indices to be included in the request.
 * @throws {Error} If the API key is empty or if there is an error during the request initialization.
 */
static initRequestForChatGPTWithoutStream (history,apikey,url,model,temperature,funcIndices=[]) {
  if (apikey.trim() === "") {
    MNUtil.showHUD(model+": No apikey!")
    return
  }
  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer "+apikey,
    Accept: "text/event-stream"
  }
    // copyJSON(headers)
  let body = {
    "model":model,
    "messages":history
  }
  // if (model !== "deepseek-reasoner") {
    body.temperature = temperature
    // if (url === "https://api.minimax.chat/v1/text/chatcompletion_v2") {
    //   let tools = chatAITool.getToolsByIndex(funcIndices,true)
    //   if (tools.length) {
    //     body.tools = tools
    //   }
    //   body.max_tokens = 8000
    // }else{
    //   let tools = chatAITool.getToolsByIndex(funcIndices,false)
    //   if (tools.length) {
    //     body.tools = tools
    //     body.tool_choice = "auto"
    //   }
    // }
  const request = MNConnection.initRequest(url, {
      method: "POST",
      headers: headers,
      timeout: 60,
      json: body
    })
  return request
}

}
class MNButton{
  static get highlightColor(){
    return UIColor.blendedColor(
      UIColor.colorWithHexString("#2c4d81").colorWithAlphaComponent(0.8),
      MNUtil.app.defaultTextColor,
      0.8
    );
  }
  /**
   *
   * @param {{color:string,title:string,bold:boolean,font:number,opacity:number,radius:number,alpha:number,scale:number,fontColor:string}} config
   * @param {UIView} superView
   */
  static new(config = {},superView){
    return new MNButton(config,superView)
    // let newButton = UIButton.buttonWithType(0);
    // newButton.autoresizingMask = (1 << 0 | 1 << 3);
    // newButton.layer.masksToBounds = true;
    // newButton.setTitleColorForState(UIColor.whiteColor(),0);
    // newButton.setTitleColorForState(this.highlightColor, 1);
    // let radius = ("radius" in config) ? config.radius : 8
    // newButton.layer.cornerRadius = radius;
    // this.setConfig(newButton, config)
    // if (superView) {
    //   superView.addSubview(newButton)
    // }
    // return newButton
  }
  static builtInProperty = [
    "superview",
    "frame",
    "bounds",
    "center",
    "window",
    "gestureRecognizers",
    "backgroundColor",
    "color",
    "hidden",
    "autoresizingMask",
    "currentTitle",
    "currentTitleColor",
    "currentImage",
    "subviews",
    "masksToBounds",
    "title",
    "alpha",
    "font",
    "opacity",
    "radius",
    "cornerRadius",
    "highlight"
  ]
  /**
   * 
   * @param {{color:string,title:string,bold:boolean,font:number,opacity:number,radius:number,alpha:number,scale:number,fontColor:string}} config 
   * @param {UIView} superView 
   * @returns 
   */
  constructor(config = {},superView){
    this.button = UIButton.buttonWithType(0);
    this.button.autoresizingMask = (1 << 0 | 1 << 3);
    this.button.layer.masksToBounds = true;
    this.button.setTitleColorForState(this.highlightColor, 1);
    let radius = ("radius" in config) ? config.radius : 8
    this.button.layer.cornerRadius = radius;
    MNButton.setConfig(this.button, config)
    this.titleLabel = this.button.titleLabel
    this.layer = this.button.layer
    if (superView) {
      superView.addSubview(this.button)
    }
    let keys = Object.keys(config)
    for (let i = 0; i < keys.length; i++) {
      if (!MNButton.builtInProperty.includes(keys[i])) {
        this.button[keys[i]] = config[keys[i]]
        this[keys[i]] = config[keys[i]]
      }
    }
    return new Proxy(this, {
      set(target, property, value) {
        target[property] = value;
        if (!MNButton.builtInProperty.includes(property)) {
          target.button[property] = value
        }
        return true;
      }
    });
  }
  /**
   * @param {UIView} view
   */
  set superview(view){
    view.addSubview(this.button)
  }
  get superview(){
    return this.button.superview
  }
  /**
   * @param {CGRect} targetFrame
   */
  set frame(targetFrame){
    this.button.frame = targetFrame
  }
  get frame(){
    return this.button.frame
  }
  set bounds(targetFrame){
    this.button.bounds = targetFrame
  }
  get bounds(){
    return this.button.bounds
  }
  set center(targetFrame){
    this.button.center = targetFrame
  }
  get center(){
    return this.button.center
  }
  get window(){
    return this.button.window
  }
  get gestureRecognizers(){
    return this.button.gestureRecognizers
  }
  get borderColor(){
    return this.button.layer.borderColor
  }
  get borderWidth(){
    return this.button.layer.borderWidth
  }
  set borderColor(color){
    this.button.layer.borderColor = color
  }
  set borderWidth(width){
    this.button.layer.borderWidth = width
  }
  /**
   * 
   * @param {UIColor|string} color 
   */
  set backgroundColor(color){
    if (typeof color === "string") {
      if(color.length > 7){
        this.button.backgroundColor = MNButton.hexColor(color)
      }else{
        this.button.backgroundColor = MNButton.hexColorAlpha(color, 1.0)
      }
    }else{
      this.button.backgroundColor = color
    }
  }
  get backgroundColor(){
    return this.button.backgroundColor
  }
  /**
   * 
   * @param {UIColor|string} color 
   */
  set color(color){
    if (typeof color === "string") {
      if(color.length > 7){
        this.button.backgroundColor = MNButton.hexColor(color)
      }else{
        this.button.backgroundColor = MNButton.hexColorAlpha(color, 1.0)
      }
    }else{
      this.button.backgroundColor = color
    }
  }
  get color(){
    return this.button.backgroundColor
  }
  get colorString(){
    return "#"+this.button.backgroundColor.hexStringValue
  }
  /**
   * 
   * @param {boolean} hidden 
   */
  set hidden(hidden){
    this.button.hidden = hidden
  }
  get hidden(){
    return this.button.hidden
  }
  /**
   * 
   * @param {number} mask 
   */
  set autoresizingMask(mask){
    this.button.autoresizingMask = mask
  }
  /**
   * 
   * @returns {number} 
   */
  get autoresizingMask(){
    return this.button.autoresizingMask
  }
  /**
   * 
   * @param {number} opacity 
   */
  set opacity(opacity){
    this.button.layer.opacity = opacity
  }
  get opacity(){
    return this.button.layer.opacity
  }
  /**
   * 
   * @param {number} radius 
   */
  set radius(radius){
    this.button.layer.cornerRadius = radius
  }
  /**
   * @returns {number}
   */
  get radius(){
    return this.button.layer.cornerRadius
  }
  /**
   * 
   * @param {number} radius 
   */
  set cornerRadius(radius){
    this.button.layer.cornerRadius = radius
  }
  get cornerRadius(){
    return this.button.layer.cornerRadius
  }
  /**
   * 
   * @param {string} title 
   */
  set currentTitle(title){
    this.button.setTitleForState(title,0)
  }
  get currentTitle(){
    return this.button.currentTitle
  }
  /**
   * 
   * @param {string} title 
   */
  set title(title){
    this.button.setTitleForState(title,0)
  }
  get title(){
    return this.button.currentTitle
  }
  /**
   * 
   * @param {string|UIColor} color 
   */
  set currentTitleColor(color){
    if (typeof color === "string") {
      if(color.length > 7){
        this.button.setTitleColorForState(MNButton.hexColor(color),0)
      }else{
        this.button.setTitleColorForState(MNButton.hexColorAlpha(color, 1.0),0)
      }
    }else{
      this.button.setTitleColorForState(color,0)
    }
  }
  get currentTitleColor(){
    return this.button.titleLabel.textColor
  }
  get currentTitleColorString(){
    return "#"+this.button.titleLabel.textColor.hexStringValue
  }
  get titleColor(){
    return this.button.titleLabel.textColor
  }
  get titleColorString(){
    return "#"+this.button.titleLabel.textColor.hexStringValue
  }
  /**
   * 
   * @param {UIImage} image 
   */
  set currentImage(image){
    this.button.setImageForState(image,0)
  }
  get currentImage(){
    return this.button.currentImage
  }
  get subviews(){
    return this.button.subviews
  }
  /**
   * 
   * @param {UIFont} font 
   */
  set font(font){
    this.button.titleLabel.font = font
  }
  get font(){
    return this.button.titleLabel.font
  }
  /**
   * 
   * @param {boolean} masksToBounds 
   */
  set masksToBounds(masksToBounds){
    this.button.layer.masksToBounds = masksToBounds
  }
  /**
   * 
   * @returns {boolean}
   */
  get masksToBounds(){
    return this.button.layer.masksToBounds
  }
  /**
   * 
   * @param {number} x 
   * @param {number} y 
   * @param {number} width 
   * @param {number} height 
   */
  setFrame(x,y,width,height){
    let frame = this.button.frame
    if (x !== undefined) {
      frame.x = x
    }else if (this.button.x !== undefined) {
      frame.x = this.button.x
    }
    if (y !== undefined) {
      frame.y = y
    }else if (this.button.y !== undefined) {
      frame.y = this.button.y
    }
    if (width !== undefined) {
      frame.width = width
    }else if (this.button.width !== undefined) {
      frame.width = this.button.width
    }
    if (height !== undefined) {
      frame.height = height
    }else if (this.button.height !== undefined) {
      frame.height = this.button.height
    }
    this.button.frame = frame
  }
  /**
   * 
   * @param {string} hexColor 
   * @param {number} [alpha=1.0] 
   */
  setColor(hexColor,alpha = 1.0){
    if(hexColor.length > 7){
      this.button.backgroundColor = MNButton.hexColor(hexColor)
    }else{
      this.button.backgroundColor = MNButton.hexColorAlpha(hexColor, alpha)
    }
  }
  setImageForState(image,state = 0){
    this.button.setImageForState(image,state)
  }
  setImage(image,state = 0){
    this.button.setImageForState(image,state)
  }
  setTitleColorForState(color,state = 0){
    this.button.setTitleColorForState(color,state)
  }
  setTitleColor(color,state = 0){
    if (typeof color === "string") {
      let realColor = MNUtil.hexColor(color)
      this.button.setTitleColorForState(realColor,state)
      return
    }
    this.button.setTitleColorForState(color,state)
  }
  setTitleForState(title,state = 0){
    this.button.setTitleForState(title,state)
  }
  setTitle(title,state = 0){
    this.button.setTitleForState(title,state)
  }
  addSubview(view){
    this.button.addSubview(view)
  }
  removeFromSuperview(){this.button.removeFromSuperview()}
  bringSubviewToFront(view){this.button.bringSubviewToFront(view)}
  sendSubviewToBack(view){this.button.sendSubviewToBack(view)}
  isDescendantOfView(view){return this.button.isDescendantOfView(view)}
  isDescendantOfStudyView(){return this.button.isDescendantOfView(MNUtil.studyView)}
  isDescendantOfCurrentWindow(){return this.button.isDescendantOfView(MNUtil.currentWindow)}
  setNeedsLayout(){this.button.setNeedsLayout()}
  layoutIfNeeded(){this.button.layoutIfNeeded()}
  layoutSubviews(){this.button.layoutSubviews()}
  setNeedsDisplay(){this.button.setNeedsDisplay()}
  sizeThatFits(size){
    return this.button.sizeThatFits(size)
  }

  /**
   * 
   * @param {any} target 
   * @param {UIControlEvents} controlEvent 
   * @param {string} action 
   */
  addTargetActionForControlEvents(target,action,controlEvent = 1 << 6){
    this.button.addTargetActionForControlEvents(target, action, controlEvent);
  }
  /**
   * 
   * @param {any} target 
   * @param {UIControlEvents} controlEvent 
   * @param {string} action 
   */
  removeTargetActionForControlEvents(target,action,controlEvent = 1 << 6){
    this.button.removeTargetActionForControlEvents(target, action, controlEvent);
  }
  /**
   * 
   * @param {any} target 
   * @param {string} selector 
   */
  addClickAction (target,selector) {
    this.button.addTargetActionForControlEvents(target, selector, 1 << 6);
  }
  /**
   * 
   * @param {UIGestureRecognizer} gestureRecognizer 
   */
  addGestureRecognizer(gestureRecognizer){
    this.button.addGestureRecognizer(gestureRecognizer)
  }
  /**
   * 
   * @param {UIGestureRecognizer} gestureRecognizer 
   */
  removeGestureRecognizer(gestureRecognizer){
    this.button.removeGestureRecognizer(gestureRecognizer)
  }
  /**
   * 
   * @param {any} target 
   * @param {string} selector 
   */
  addPanGesture (target,selector) {
    let gestureRecognizer = new UIPanGestureRecognizer(target,selector)
    this.button.addGestureRecognizer(gestureRecognizer)
  }

  /**
   * 
   * @param {any} target 
   * @param {string} selector 
   */
  addLongPressGesture (target,selector,duration = 0.3) {
    let gestureRecognizer = new UILongPressGestureRecognizer(target,selector)
    gestureRecognizer.minimumPressDuration = duration
    this.button.addGestureRecognizer(gestureRecognizer)
  }
  /**
   * 
   * @param {any} target 
   * @param {string} selector 
   */
  addSwipeGesture (target,selector) {
    let gestureRecognizer = new UISwipeGestureRecognizer(target,selector)
    this.button.addGestureRecognizer(gestureRecognizer)
  }
//   static createButton(superview,config) {
//     let button = UIButton.buttonWithType(0);
//     button.autoresizingMask = (1 << 0 | 1 << 3);
//     button.setTitleColorForState(UIColor.whiteColor(),0);
//     button.setTitleColorForState(this.highlightColor, 1);
//     button.backgroundColor = this.hexColorAlpha("#9bb2d6",0.8)
//     button.layer.cornerRadius = 8;
//     button.layer.masksToBounds = true;
//     button.titleLabel.font = UIFont.systemFontOfSize(16);
//     if (superview) {
//       superview.addSubview(button)
//     }
//     this.setConfig(button, config)
//     return button
// }
  /**
   * Creates a color from a hex string with an optional alpha value.
   * 
   * This method takes a hex color string and an optional alpha value, and returns a UIColor object.
   * If the alpha value is not provided, the color is returned without modifying its alpha component.
   * 
   * @param {string} hex - The hex color string (e.g., "#RRGGBB").
   * @param {number} [alpha=1.0] - The alpha value (opacity) of the color, ranging from 0.0 to 1.0.
   * @returns {UIColor} The UIColor object representing the specified color with the given alpha value.
   */
  static hexColorAlpha(hex,alpha) {
    let color = UIColor.colorWithHexString(hex)
    return alpha!==undefined?color.colorWithAlphaComponent(alpha):color
  }
  /**
   * function to create a color from a hex string
   * @param {string} hex 
   * @returns {UIColor}
   */
  static hexColor(hex) {
    let colorObj = MNUtil.parseHexColor(hex)
    return this.hexColorAlpha(colorObj.color,colorObj.opacity)
  }
  /**
   * 
   * @param {UIButton} button 
   * @param {string} hexColor 
   * @param {number} [alpha=1.0] 
   */
  static setColor(button,hexColor,alpha = 1.0){
    if(hexColor.length > 7){
      button.backgroundColor = this.hexColor(hexColor)
    }else{
      button.backgroundColor = this.hexColorAlpha(hexColor, alpha)
    }
  }
  /**
   * 
   * @param {UIButton} button 
   * @param {string} title 
   * @param {number} font = 16 
   * @param {boolean} bold= false 
   * @param {string} fontColor = "#ffffff" 
   */
  static setTitle(button,title,font = 16,bold= false,fontColor = "#ffffff"){
    button.setTitleColorForState(this.hexColor(fontColor),0)
    button.setTitleForState(title,0)
    if (bold) {
      button.titleLabel.font = UIFont.boldSystemFontOfSize(font)
    }else{
      button.titleLabel.font = UIFont.systemFontOfSize(font)
    }
  }
  /**
   *
   * @param {UIButton} button
   * @param {string|NSData} path
   */
  static setImage(button,path,scale){
    if (typeof path === "string") {
      button.setImageForState(MNUtil.getImage(path,scale),0)
    }else{
      button.setImageForState(path, 0)
    }
  }
  static setOpacity(button,opacity){
    button.layer.opacity = opacity


  }
  static setRadius(button,radius = 8){
    button.layer.cornerRadius = radius;
  }
/**
   * 设置按钮的配置
   *
   * @param {UIButton} button - 要设置配置的按钮对象
   * @param {{color: string, title: string, bold: boolean, font: number, opacity: number, radius: number, image?: string, scale?: number}} config - 配置对象
   */
  static setConfig(button, config) {
    if ("color" in config) {
      this.setColor(button, config.color, config.alpha);
    }
    if ("title" in config) {
      this.setTitle(button, config.title, config.font, config.bold, config.fontColor);
    }
    if ("opacity" in config) {
      this.setOpacity(button, config.opacity);
    }
    if ("radius" in config) {
      this.setRadius(button, config.radius);
    }
    if ("image" in config) {
      this.setImage(button, config.image, config.scale);
    }
    if ("highlight" in config) {
      button.setTitleColorForState(config.highlight, 1)
    }
  }
  /**
   * 
   * @param {UIView} button 
   * @param {any} target 
   * @param {string} selector 
   */
  static addClickAction (button,target,selector) {
    button.addTargetActionForControlEvents(target, selector, 1 << 6);
    
  }
  /**
   * 
   * @param {UIView} button 
   * @param {any} target 
   * @param {string} selector 
   */
  static addPanGesture (button,target,selector) {
    let gestureRecognizer = new UIPanGestureRecognizer(target,selector)
    button.addGestureRecognizer(gestureRecognizer)
  }

  /**
   * 
   * @param {UIView} button 
   * @param {any} target 
   * @param {string} selector 
   */
  static addLongPressGesture (button,target,selector,duration = 0.3) {
    let gestureRecognizer = new UILongPressGestureRecognizer(target,selector)
    gestureRecognizer.minimumPressDuration = duration
    button.addGestureRecognizer(gestureRecognizer)
  }
  /**
   * 
   * @param {UIView} button 
   * @param {any} target 
   * @param {string} selector 
   */
  static addSwipeGesture (button,target,selector) {
    let gestureRecognizer = new UISwipeGestureRecognizer(target,selector)
    button.addGestureRecognizer(gestureRecognizer)
  }

}
class MNExtensionPanel {
  static subviews = {}
  static get currentWindow(){
    //关闭mn4后再打开，得到的focusWindow会变，所以不能只在init做一遍初始化
    return this.app.focusWindow
  }
  static get subviewNames(){
    return Object.keys(this.subviews)
  }
  static get app(){
    // this.appInstance = Application.sharedInstance()
    // return this.appInstance
    if (!this.appInstance) {
      this.appInstance = Application.sharedInstance()
    }
    return this.appInstance
  }
  static get studyController(){
    return this.app.studyController(this.currentWindow)
  }
  /**
   * @returns {{view:UIView}}
   **/
  static get controller(){
    return this.studyController.extensionPanelController
  }
  /**
   * @returns {UIView}
   */
  static get view(){
    return this.studyController.extensionPanelController.view
  }
  static get frame(){
    return this.view.frame
  }
  static get width(){
    return this.view.frame.width
  }
  static get height(){
    return this.view.frame.height
  }
  static get on(){
    if (this.controller && this.view.window) {
      return true
    }
    return false
  }
  /**
   * 用于关闭其他窗口的扩展面板
   * @param {UIWindow} window 
   */
  static hideExtentionPanel(window){
    let originalStudyController = this.app.studyController(window)
    if (originalStudyController.extensionPanelController.view.window) {
      originalStudyController.toggleExtensionPanel()
    }
  }
  static toggle(){
    this.studyController.toggleExtensionPanel()
  }
  static show(name = undefined){
    if (!this.on) {
      this.toggle()
      MNUtil.delay(0.1).then(()=>{
        if (!this.on) {
          this.toggle()
        }
      })
    }
    if (name && name in this.subviews) {
      let allNames = Object.keys(this.subviews)
      allNames.forEach(n=>{
        let view = this.subviews[n]
        if (n == name){
          if (!view.isDescendantOfView(this.view)) {
            this.hideExtentionPanel(view.window)
            view.removeFromSuperview()
            this.view.addSubview(view)
          }
          view.hidden = false
        }else{
          view.hidden = true
        }
      })
    }
  }
  /**
   * 
   * @param {string} name 
   * @returns {UIView}
   */
  static subview(name){
    return this.subviews[name]
  }
  /**
   * 需要提供一个视图名,方便索引和管理
   * @param {string} name 
   * @param {UIView} view 
   */
  static addSubview(name,view){
    if (this.controller) {
      this.subviews[name] = view
      this.view.addSubview(view)
      let allNames = Object.keys(this.subviews)
      allNames.forEach(n=>{
        if (n == name){
          this.subviews[n].hidden = false
        }else{
          this.subviews[n].hidden = true
        }
      })
    }else{
      MNUtil.showHUD("Show Extension Panel First!")
    }
  }
  static removeSubview(name){
    if (name in this.subviews) {
      this.subviews[name].removeFromSuperview()
      delete this.subviews[name]
    }
  }
}

class DataConverter {
  static errorLog = []
  /**
   * 
   * @param {string|{message:string,level:string,source:string,timestamp:number,detail:string}} error 
   * @param {string} source = "DataConverter"
   * @param {string} info 
   */
  static addErrorLog(error,source = "DataConverter",info){
    MNUtil.showHUD("DataConverter Error ("+source+"): "+error)
    let tem = {source:source,time:(new Date(Date.now())).toString()}
    if (typeof error === "string") {
      tem.error = error
    }else{
      if (error.detail) {
        tem.error = {message:error.message,detail:error.detail}
      }else{
        tem.error = error.message
      }
    }
    if (info) {
      tem.info = info
    }
    MNUtil.errorLog.push(tem)
    MNUtil.copyJSON(this.errorLog)
    MNUtil.log({
      message:source,
      level:"ERROR",
      source:"DataConverter",
      timestamp:Date.now(),
      detail:tem
    })
  }
static customBtoa(str) {
    var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
    var output = '';
    var idx = 0;
    
    // 确保输入是字符串
    str = String(str);
    
    while (idx < str.length) {
        // 每次读取 3 个字节
        var c1 = str.charCodeAt(idx++);
        var c2 = str.charCodeAt(idx++);
        var c3 = str.charCodeAt(idx++);

        // 将 3 个 8位字节 转换为 4 个 6位索引
        var e1 = c1 >> 2;
        // c1 的后2位 + c2 的前4位
        var e2 = ((c1 & 3) << 4) | (c2 >> 4);
        // c2 的后4位 + c3 的前2位
        var e3 = ((c2 & 15) << 2) | (c3 >> 6);
        // c3 的后6位
        var e4 = c3 & 63;

        // 处理填充逻辑 (=)
        // 如果 c2 是 NaN (也就是字符串结束了)，e3 和 e4 都应该是填充符
        if (isNaN(c2)) {
            e3 = e4 = 64; // 64 对应 chars 里的 '='
        } 
        // 如果 c3 是 NaN，e4 应该是填充符
        else if (isNaN(c3)) {
            e4 = 64;
        }

        output += chars.charAt(e1) + chars.charAt(e2) + chars.charAt(e3) + chars.charAt(e4);
    }
    
    return output;
}
static utf8_to_b64(str) {//备用
    // 第一步：使用 encodeURIComponent 将宽字符转换成 UTF-8 编码的百分号序列
    // 第二步：使用 replace 将百分号序列 (%XX) 还原为单字节字符
    var binaryStr = encodeURIComponent(str).replace(/%([0-9A-F]{2})/g,
        function(match, p1) {
            return String.fromCharCode('0x' + p1);
        });
    
    // 第三步：调用上面的基础版 btoa
    return this.customBtoa(binaryStr);
}
/**
 * 压缩配置,pako压缩效率高，但更消耗资源和时间,lz-string压缩效率低，但更节省资源和时间
 * @param {object} jsonObj - 要编码的 JSON 对象
 * @param {"pako"|"lz-string"} type - 压缩方式，pako或lz-string
 * @returns {string} - 生成的 Base64 字符串
 */
static compressAndEncode(jsonObj,type = "pako") {
  try {
    const jsonString = JSON.stringify(jsonObj);
    if (type == "pako") {
      // 1. Gzip 压缩 (得到 Uint8Array)
      const compressedUint8 = pako.gzip(jsonString);
      const base64 = this.uint8ArrayToBase64(compressedUint8);
      return base64;
    }
    if (type == "lz-string") {
      const base64 = LZString.compressToBase64(jsonString);
      return base64;
    }
    
  } catch (error) {
    this.addErrorLog(error, "compressAndEncode")
    return undefined
  }
}
/**
 * 解码 Base64 字符串，并使用 gzip 解压
 * @param {string} base64 - 要解码的 Base64 字符串
 * @returns {string} - 解压后的字符串，如果是json字符串需要自行parse为对象
 */
static decodeAndDecompress(base64,type = "pako") {
  try {
    if (type == "pako") {
      const binData = this.base64ToUint8Array(base64)
      // 3. Gzip 解压
      // 使用 pako.ungzip 进行解压
      const decompressedData = pako.ungzip(binData, { to: 'string' });
      return decompressedData
    }
    if (type == "lz-string") {
      const decompressedData = LZString.decompressFromBase64(base64);
      return decompressedData
    }
  } catch (error) {
    this.addErrorLog(error, "decodeAndDecompress")
    return undefined
  }
}

/**
 * 对齐原生 atob：Base64 字符串 → 二进制字符串
 * 增强点：自动清洗前缀/换行/空格（原生 atob 不支持，会报错）
 * @param {string} base64Str - Base64 编码字符串（支持带前缀/脏数据）
 * @returns {string} 二进制字符串（每个字符对应一个字节，范围 0-255）
 */
static atob(base64Str) {
  // Step 1: 用自定义的 base64ToUint8Array 解码（增强清洗逻辑）
  const uint8 = this.base64ToUint8Array(base64Str);
  
  // Step 2: Uint8Array → 二进制字符串（对齐原生输出）
  // 优化：用 String.fromCharCode 批量转换（性能优于循环拼接）
  return String.fromCharCode.apply(null, uint8);
}
/**
 * 对齐原生 btoa：二进制字符串 → Base64 字符串
 * 增强点：自动兼容 Uint8Array 输入（原生 btoa 不支持，会报错）
 * @param {string|Uint8Array} input - 二进制字符串 或 Uint8Array
 * @returns {string} Base64 编码字符串
 * @throws {Error} 输入非二进制字符串/Uint8Array 时抛出错误（对齐原生）
 */
static btoa(input) {
  let uint8;
  
  // Step 1: 处理输入（对齐原生 + 增强兼容）
  if (typeof input === 'string') {
    // 原生 btoa 要求输入是二进制字符串（每个字符 ≤ 0xFF），这里做校验（对齐原生行为）
    for (let i = 0; i < input.length; i++) {
      if (input.charCodeAt(i) > 0xFF) {
        throw new Error('btoa() failed: The string to be encoded contains characters outside of the Latin1 range.');
      }
    }
    // 二进制字符串 → Uint8Array（供后续编码）
    uint8 = new Uint8Array(input.length);
    for (let i = 0; i < input.length; i++) {
      uint8[i] = input.charCodeAt(i);
    }
  } else if (input instanceof Uint8Array) {
    // 增强：直接支持 Uint8Array 输入（原生 btoa 不支持）
    uint8 = input;
  } else {
    // 对齐原生：输入类型错误时抛出（原生 btoa 只接受 string）
    throw new TypeError('btoa() argument must be a string or Uint8Array.');
  }
  
  // Step 2: 用自定义的 uint8ArrayToBase64 编码（高性能）
  return this.uint8ArrayToBase64(uint8);
}

static async convertImageBase64ToPdfBase64(pngBase64){
  try{
    let pdfBase64 = await PDFTools.convertImageBase64ToPdfBase64(pngBase64)
    return pdfBase64
  }catch(error){
    this.addErrorLog(error, "convertImageBase64ToPdfBase64")
    return undefined
  }
}
static async convertImageDataToPdfData(imageData){
  let imageBase64 = imageData.base64Encoding()
  let pdfBase64 = await this.convertImageBase64ToPdfBase64(imageBase64)
  let pdfData = this.dataFromBase64(pdfBase64,"pdf")
  return pdfData
}

  static rgbaToHex(rgba, includeAlpha = false, toUpperCase = false) {
      // 确保RGB分量在0-255范围内
      const r = Math.max(0, Math.min(255, Math.round(rgba.r)));
      const g = Math.max(0, Math.min(255, Math.round(rgba.g)));
      const b = Math.max(0, Math.min(255, Math.round(rgba.b)));

      // 确保alpha分量在0-1范围内
      const a = Math.max(0, Math.min(1, rgba.a));

      // 将每个颜色分量转换为两位的十六进制
      const rHex = r.toString(16).padStart(2, '0');
      const gHex = g.toString(16).padStart(2, '0');
      const bHex = b.toString(16).padStart(2, '0');

      let hex;
      if (includeAlpha) {
        // 将alpha分量从0-1转换为0-255，然后转换为两位的十六进制
        const aHex = Math.round(a * 255).toString(16).padStart(2, '0');
        // 组合成8位HEX颜色值
        hex = `#${rHex}${gHex}${bHex}${aHex}`;
      } else {
        // 组合成6位HEX颜色值
        hex = `#${rHex}${gHex}${bHex}`;
      }

      // 根据参数决定是否转换为大写
      return toUpperCase ? hex.toUpperCase() : hex;
  }
  static rgbaArrayToHexArray(rgbaArray, includeAlpha = false, toUpperCase = false) {
    return rgbaArray.map(rgba => this.rgbaToHex(rgba,includeAlpha,toUpperCase));
  }
    /**
     * 将十六进制颜色转换为 RGB 数组。
     * @param {string} hex - 十六进制颜色字符串。
     * @returns {Array<number>} - RGB 数组 [r, g, b]。
     */
    static hexToRgb(hex) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return [r, g, b];
    }
  static pngToJpg(pngData,quality = 0.1){
    let jpgData = UIImage.imageWithData(pngData).jpegData(quality)
    return jpgData
  }
  static compressImageToJpg(imageData,quality = 0.1){
    let compressedData
    switch (typeof imageData) {
      case "string":
        if (imageData.startsWith("data:image/jpeg;base64,") || imageData.startsWith("data:image/png;base64,")) {
          let data = this.dataFromBase64(imageData)
          compressedData = UIImage.imageWithData(data).jpegData(quality)
          return compressedData;
        }else{
          let data = this.dataFromBase64(base64,"png")
          compressedData = UIImage.imageWithData(data).jpegData(quality)
          return compressedData;
        }
        break;
      case "NSData":
        compressedData = UIImage.imageWithData(imageData).jpegData(quality)
        return compressedData;
      case "UIImage":
        compressedData = imageData.jpegData(quality)
        return compressedData;
        break;
      default:
        break;
    }
    return undefined
  }
  static imageFromBase64(base64,type = "png"){
    let data = this.dataFromBase64(base64,type)
    let image = UIImage.imageWithData(data)
    return image
  }
  static dataFromBase64(base64,type = undefined){
    if (base64.startsWith("data:")) {//如果是data url，则直接获取
      let data = NSData.dataWithContentsOfURL(MNUtil.genNSURL(base64))
      return data
    }
    if (type) {
      switch (type) {
        case "pdf":
          let pdfData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:application/pdf;base64,"+base64))
          return pdfData
        case "png":
          let pngData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:image/png;base64,"+base64))
          return pngData
        case "jpg":
        case "jpeg":
          let jpegData = NSData.dataWithContentsOfURL(MNUtil.genNSURL("data:image/jpeg;base64,"+base64))
          return jpegData
        default:
          break;
      }
    }
    //没有指定类型，且不是data url，则认为是application/octet-stream
    let url = MNUtil.genNSURL("data:application/octet-stream;base64,"+base64)
    return NSData.dataWithContentsOfURL(url)
  }
  /**
   * Generates a frame object with the specified x, y, width, and height values.
   * 
   * This method creates a frame object with the provided x, y, width, and height values.
   * If any of these values are undefined, it displays a HUD message indicating the invalid parameter
   * and sets the value to 10 as a default.
   * 
   * @param {number} x - The x-coordinate of the frame.
   * @param {number} y - The y-coordinate of the frame.
   * @param {number} width - The width of the frame.
   * @param {number} height - The height of the frame.
   * @returns {{x: number, y: number, width: number, height: number}} The frame object with the specified dimensions.
   */
  static genFrame(x, y, width, height) {
    if (x === undefined) {
        MNUtil.showHUD("无效的参数: x");
        x = 10;
    }
    if (y === undefined) {
        MNUtil.showHUD("无效的参数: y");
        y = 10;
    }
    if (width === undefined) {
        MNUtil.showHUD("无效的参数: width");
        // MNUtil.copyJSON({x:x,y:y,width:width,height:height})
        width = 10;
    }
    if (height === undefined) {
        MNUtil.showHUD("无效的参数: height");
        height = 10;
    }
    return { x: x, y: y, width: width, height: height };
  }
  static parseWinRect(winRect) {
    let rectArr = winRect.replace(/{/g, '').replace(/}/g, '').replace(/\s/g, '').split(',')
    let X = Number(rectArr[0])
    let Y = Number(rectArr[1])
    let H = Number(rectArr[3])
    let W = Number(rectArr[2])
    return this.genFrame(X, Y, W, H)
  }
/**
 * 辅助方法：将输入的时间转换为 JS Date 对象
 * @param {string|Date|number} date - 输入的时间数据
 * @returns {Date|null}
 */
static convertDate(date) {
  // 1. 如果是 null 或 undefined，返回 null
  if (!date) return null;
  // 2. 如果已经是 Date 对象，直接返回
  if (date instanceof Date) return date;
  // 3. 如果是字符串或时间戳，尝试转换
  const d = new Date(date);
  // 4. 检查是否转换为了有效时间 (避免 Invalid Date)
  return isNaN(d.getTime()) ? null : d;
}
/**
 * 将 NSFileManager 返回的文件属性对象转换为 Node.js fs.Stats 格式
 * @param {Object} nsAttrs - NSFileManager 获取的文件属性
 * @returns {Object} - 模拟 Node.js fs.Stats 的对象
 */
  static convertNsAttrsToFsStats(nsAttrs) {
  // 处理时间：ISO 字符串 → Date 对象

  // 处理权限：NSFilePosixPermissions（十进制）→ Node.js mode（八进制）
  const mode = nsAttrs.NSFilePosixPermissions ? 
    `0o${nsAttrs.NSFilePosixPermissions.toString(8)}` : null;

  // 构建模拟的 Stats 对象
  const stats = {
    // 核心属性（与 Node.js fs.Stats 对齐）
    dev: nsAttrs.NSFileSystemNumber || 0,       // 设备 ID（对应 NSFileSystemNumber）
    ino: nsAttrs.NSFileSystemFileNumber || 0,   // inode 编号（对应 NSFileSystemFileNumber）
    mode: mode ? parseInt(mode, 8) : 0,         // 权限模式（八进制）
    nlink: nsAttrs.NSFileReferenceCount || 1,   // 硬链接数（对应 NSFileReferenceCount）
    uid: nsAttrs.NSFileOwnerAccountID || 0,     // 用户 ID（对应 NSFileOwnerAccountID）
    gid: nsAttrs.NSFileGroupOwnerAccountID || 0,// 组 ID（对应 NSFileGroupOwnerAccountID）
    rdev: 0,                                    // 特殊设备 ID（NSFileManager 无直接对应，默认 0）
    size: nsAttrs.NSFileSize || 0,              // 文件大小（对应 NSFileSize）
    blksize: 4096,                              // 块大小（NSFileManager 无直接对应，默认 4096）
    blocks: nsAttrs.NSFileSize ? Math.ceil(nsAttrs.NSFileSize / 4096) : 0, // 块数（计算值）
    atimeMs: this.convertDate(nsAttrs.NSFileModificationDate)?.getTime() || 0, // 最后访问时间（NSFileManager 无直接对应，暂用修改时间）
    mtimeMs: this.convertDate(nsAttrs.NSFileModificationDate)?.getTime() || 0, // 最后修改时间（对应 NSFileModificationDate）
    ctimeMs: this.convertDate(nsAttrs.NSFileCreationDate)?.getTime() || 0,     // 状态改变时间（对应 NSFileCreationDate）
    birthtimeMs: this.convertDate(nsAttrs.NSFileCreationDate)?.getTime() || 0, // 创建时间（对应 NSFileCreationDate）

    // 时间对象（Node.js Stats 同时提供 ms 和 Date 对象两种格式）
    atime: this.convertDate(nsAttrs.NSFileModificationDate) || new Date(0),
    mtime: this.convertDate(nsAttrs.NSFileModificationDate) || new Date(0),
    ctime: this.convertDate(nsAttrs.NSFileCreationDate) || new Date(0),
    birthtime: this.convertDate(nsAttrs.NSFileCreationDate) || new Date(0),

    // NSFileManager 特有的属性（保留供参考）
    _nsFileType: nsAttrs.NSFileType,
    _nsFileOwnerAccountName: nsAttrs.NSFileOwnerAccountName,
    _nsFileGroupOwnerAccountName: nsAttrs.NSFileGroupOwnerAccountName,
    _nsFileProtectionKey: nsAttrs.NSFileProtectionKey,
    _nsFileExtendedAttributes: nsAttrs.NSFileExtendedAttributes
  };

  // 添加类型判断方法（模拟 Node.js Stats 的 isFile()/isDirectory() 等）
  stats.isFile = stats._nsFileType === 'NSFileTypeRegular';
  stats.isDirectory = stats._nsFileType === 'NSFileTypeDirectory';
  stats.isSymbolicLink = stats._nsFileType === 'NSFileTypeSymbolicLink';
  stats.isFIFO = stats._nsFileType === 'NSFileTypeFIFO';
  stats.isSocket = stats._nsFileType === 'NSFileTypeSocket';
  stats.isBlockDevice = stats._nsFileType === 'NSFileTypeBlockSpecial';
  stats.isCharacterDevice = stats._nsFileType === 'NSFileTypeCharacterSpecial';

  return stats;
}
/**
 * 获取文件属性
 * @param {string} path 
 * @returns {Object}
 * @property {number} size 文件大小
 * @property {number} atimeMs 最后访问时间
 * @property {number} mtimeMs 最后修改时间
 * @property {number} ctimeMs 状态改变时间
 * @property {number} birthtimeMs 创建时间
 * @property {Date} atime 最后访问时间
 * @property {Date} mtime 最后修改时间
 * @property {Date} ctime 状态改变时间
 * @property {Date} birthtime 创建时间
 * @property {string} path 文件路径
 */
  static getFileAttributes(path){
    let fileManager = NSFileManager.defaultManager()
    let attributes = fileManager.attributesOfItemAtPath(path)
    attributes = this.convertNsAttrsToFsStats(attributes)
    attributes.path = path
    return attributes
  }
  static isNSNull(obj){
    return (obj === NSNull.new())
  }
  /**
   * 
   * @param {string} jsonString 
   * @returns {object|undefined}
   */
static getValidJSON(jsonString,debug = false) {
  try {
    if (typeof jsonString === "object") {
      return jsonString
    }
    return JSON.parse(jsonString)
  } catch (error) {
    try {
      return JSON.parse(jsonrepair(jsonString))
    } catch (error) {
      let errorString = error.toString()
      try {
        if (errorString.startsWith("Unexpected character \"{\" at position")) {
          return JSON.parse(jsonrepair(jsonString+"}"))
        }
        return {}
      } catch (error) {
        debug && this.addErrorLog(error, "getValidJSON", jsonString)
        return {}
      }
    }
  }
}
  /**
   * Parses a 6/8-digit hexadecimal color string into a color object.
   * 
   * @param {string} hex - The 6/8-digit hexadecimal color string to parse.
   * @returns {object} An object with the following properties: `color` (the parsed color string), and `opacity` (the opacity of the color).
   */
  static parseHexColor(hex) {
    // 检查输入是否是有效的6位16进制颜色字符串
    if (typeof hex === 'string' && hex.length === 7) {
          return {
              color: hex,
              opacity: 1
          };
    }
    // 检查输入是否是有效的8位16进制颜色字符串
    if (typeof hex !== 'string' || !/^#([0-9A-Fa-f]{8})$/.test(hex)) {
        throw new Error('Invalid 8-digit hexadecimal color');
    }

    // 提取红色、绿色、蓝色和不透明度的16进制部分
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const a = parseInt(hex.slice(7, 9), 16) / 255; // 转换为0到1的不透明度

    // 将RGB值转换为6位16进制颜色字符串
    const rgbHex = `#${hex.slice(1, 7)}`;

    return {
        color: rgbHex,
        opacity: parseFloat(a.toFixed(2)) // 保留2位小数
    };
  }
  static hexColorAlpha(hex,alpha=1.0) {
    let color = UIColor.colorWithHexString(hex)
    return alpha!==undefined?color.colorWithAlphaComponent(alpha):color
  }
  /**
   * 
   * @param {string} hex 
   * @returns {UIColor}
   */
  static hexColor(hex) {
    let colorObj = this.parseHexColor(hex)
    return MNUtil.hexColorAlpha(colorObj.color,colorObj.opacity)
  }
  static genNSURL(url) {
    return NSURL.URLWithString(url)
  }
  static string2data(string){
    return NSData.dataWithStringEncoding(string, 4)
  }
  /**
   * Converts NSData to a string.
   * 
   * 
   * @param {NSData} data - The data object to be converted to a string.
   * @returns {string} The converted string.
   */
  static dataToString(data){
    if (data instanceof NSData) {
      return NSString.stringWithContentsOfData(data)
    }
    return data
  }
  /**
   * 
   * @param {object} object 
   * @returns 
   */
  static stringify(object){
    return JSON.stringify(object, undefined, 2)
  }
  /**
   * Encrypts or decrypts a string using XOR encryption with a given key.
   * 
   * This method performs XOR encryption or decryption on the input string using the provided key.
   * Each character in the input string is XORed with the corresponding character in the key,
   * repeating the key if it is shorter than the input string. The result is a new string
   * where each character is the XOR result of the original character and the key character.
   * 
   * @param {string} input - The input string to be encrypted or decrypted.
   * @param {string} key - The key used for XOR encryption or decryption.
   * @returns {string} The encrypted or decrypted string.
   */
  static xorEncryptDecrypt(input, key) {
  try {
    if (!key) throw new Error("Key cannot be empty"); // 提前校验key非空
    let output = [];
    let result = "";
    const chunkSize = 10000; // 分块大小（根据引擎性能调整）
    for (let i = 0; i < input.length; i++) {
      const code = input.charCodeAt(i) ^ key.charCodeAt(i % key.length);
      output.push(code);
      // 分块转换：当数组达到chunkSize时，批量生成字符串并清空临时数组
      if (output.length >= chunkSize) {
        result += String.fromCharCode(...output); // 用扩展运算符（...）代替apply，或直接循环拼接
        output = [];
      }
    }
    // 处理剩余的码点
    result += String.fromCharCode(...output);
    return result;
  } catch (error) {
    this.addErrorLog(error, "xorEncryptDecrypt");
    return undefined;
  }
}
static md5FromBase64(base64Str) {
  // 1. 同样先补全
  let output = base64Str.replace(/-/g, '+').replace(/_/g, '/');
  switch (output.length % 4) {
    case 2: output += '=='; break;
    case 3: output += '='; break;
  }

  // 2. Base64 → WordArray（原始字节）
  const wordArray = CryptoJS.enc.Base64.parse(output);

  // 3. 直接算 MD5
  return CryptoJS.MD5(wordArray).toString(CryptoJS.enc.Hex);
}

static sha256FromBase64(base64Str) {
  // 1. 同样先补全
  let output = base64Str.replace(/-/g, '+').replace(/_/g, '/');
  switch (output.length % 4) {
    case 2: output += '=='; break;
    case 3: output += '='; break;
  }

  // 2. Base64 → WordArray（原始字节）
  const wordArray = CryptoJS.enc.Base64.parse(output);

  // 3. 直接算 SHA256
  return CryptoJS.SHA256(wordArray).toString(CryptoJS.enc.Hex);
}
  /**
   * 
   * @param {NSData|string} data 
   * @returns {string}
   */
  static MD5(data){
    if (typeof data === "string") {
      let md5 = CryptoJS.MD5(data).toString();
      return md5
    }
    if (data instanceof NSData) {
      let md5 = this.md5FromBase64(data.base64Encoding())
      return md5
    }
    return undefined
  }
  static parseMNImageURL(MNImageURL){
    if (MNImageURL.includes("markdownimg/png/")) {
      let hash = MNImageURL.split("markdownimg/png/")[1]
      MNUtil.imageTypeCache[hash] = "png"
      return {
        hash: hash,
        type: "png",
        ext: "png"
      }
    }else if (MNImageURL.includes("markdownimg/jpeg/")) {
      let hash = MNImageURL.split("markdownimg/jpeg/")[1]
      MNUtil.imageTypeCache[hash] = "jpeg"
      return {
        hash: hash,
        type: "jpeg",
        ext: "jpg"
      }
    }
    return undefined
  }
  static getMNImageURL(hash,type = "png"){
    if (hash in MNUtil.imageTypeCache) {
      type = MNUtil.imageTypeCache[hash]
    }
    return `marginnote4app://markdownimg/${type}/${hash}`
  }
  static getImageDataFromMNImageURL(MNImageURL){
    let imageConfig = this.parseMNImageURL(MNImageURL)
    let hash = imageConfig.hash
    let imageData = MNUtil.getMediaByHash(hash)
    return imageData
  }
  static getImageFromMNImageURL(MNImageURL){
    let imageData = this.getImageDataFromMNImageURL(MNImageURL)
    return UIImage.imageWithData(imageData)
  }
  /**
   * 从多种url中获取图片数据
   * @param {string} url 
   * @returns {NSData|undefined}
   */
  static getImageDataFromURL(url){
    if (url.startsWith("marginnote4app://markdownimg/")) {
      return this.getImageDataFromMNImageURL(url)
    }
    if (url.startsWith("data:")) {
      return this.dataFromBase64(url)
    }
    let imageData = NSData.dataWithContentsOfURL(MNUtil.genNSURL(url))
    return imageData
  }
  static imageToBase64URL(imageData,type = "png") {
    if (type === "jpg") {
      type = "jpeg"
    }
    return "data:image/png;base64,"+imageData.base64Encoding()
  }
  static imageFromWebURLSync(url) {
    let imageData = NSData.dataWithContentsOfURL(MNUtil.genNSURL(url))
    let image = UIImage.imageWithData(imageData)
    return image
  }
  static imageDataFromWebURLSync(url,type = "png",compressionQuality = 0.1) {
    let image = this.imageFromWebURLSync(url)
    if (type === "png") {
      return image.pngData()
    }
    if (type === "jpg" || type === "jpeg") {
      return image.jpegData(compressionQuality)
    }
    return image.pngData()
  }
  static async imageFromWebURL(url) {
    let res = await MNConnection.fetchDev(url)
    if (!res.ok) {
      return undefined
    }
    let imageData = res.body
    let image = UIImage.imageWithData(imageData)
    return image
  }
  static async imageDataFromWebURL(url) {
    let res = await MNConnection.fetchDev(url)
    if (!res.ok) {
      return undefined
    }
    return res.body
  }
/**
 * NSValue can't be read by JavaScriptCore, so we need to convert it to string.
 */
static NSValue2String(v) {
  return Database.transArrayToJSCompatible([v])[0]
}
/**
 * 
 * @param {NSValue} v 
 * @returns {CGSize}
 */
static NSValue2CGSize(v) {
  let sizeString = this.NSValue2String(v)
  let size = sizeString.match(/\d+/g).map(k => Number(k))
  return {width: size[0], height: size[1]}
}
/**
 * 
 * @param {NSValue} v 
 * @returns {CGRect}
 */
static NSValue2CGRect(v) {
  let rectString = this.NSValue2String(v)
  let rect = rectString.match(/\d+/g).map(k => Number(k))
  return {x: rect[0], y: rect[1], height: rect[2], width: rect[3]}
}
  /**
   * 
   * @param {string} str 
   * @returns {CGRect}
   */
  static CGRectString2CGRect(str) {
  const arr = str.match(/\d+\.?\d+/g).map(k => Number(k))
  return {
    x: arr[0],
    y: arr[1],
    height: arr[2],
    width: arr[3]
  }
}
static stringFromCharCode(char) {
  if (typeof char === 'string') {
    return String.fromCharCode(Number(char))
  }
  return String.fromCharCode(char)
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
    MNUtil.addErrorLog(error,"extractPDFPage")
    return undefined
  }
  }
/**
 * 
 * @param {string} content,必须是data url
 * @returns 
 */
static fileTypeFromBase64URL(content) {
  try{
  let tem = content.split(",")
  let prefix = tem[0]
  if (prefix.includes("octet-stream")) {//需要进一步判断
    //通过base64前几个字符判断
    let type = this.getFileTypeFromBase64(content)
    return type
  }
  if (prefix.includes("application/pdf")) {
    return "pdf"
  }
  if (prefix.includes("html")) {
    return "html"
  }
  if (prefix.includes("image/png")) {
    return "png"
  }
  if (prefix.includes("image/jpeg")) {
    return "jpg"
  }
  if (prefix.includes("markdown")){
    return "markdown"
  }
  if (prefix.includes("zip")){
    return "zip"
  }
  }catch(error){
    this.addErrorLog(error, "fileTypeFromBase64")
    return 'unknown';
  }
}
/**
 * 
 * @param {NSData} data 
 * @returns {string} 文件头十六进制字符串
 */
static hexHeaderFromData(data) {
  try {
    let subData = data.subdataWithRange({location:0,length:16})
    let base64 = subData.base64Encoding()
    const uint8Array = DataConverter.base64ToUint8Array(base64)
    const fileHeaderBytes = uint8Array.slice(0, 16); // 取前 16 字节文件头
    const hexHeader = Array.from(fileHeaderBytes)
      .map(byte => byte.toString(16).padStart(2, '0').toUpperCase())
      .join('');
    return hexHeader
  } catch (error) {
    this.addErrorLog(error, "hexHeaderFromData")
    return undefined
  }
}
/**
 * 直接从 Base64 格式的 Data URL 判断文件格式，仅用于不能直接判断base64类型的情况
 * @param {string} base64 - Base64 Data URL（如 data:application/octet-stream;base64,...）
 * @returns {string} 文件格式（如 'jpg', 'png', 'pdf' 等，未知则返回 'unknown'）
 */
static getFileTypeFromBase64(base64) {
  try {
    let data = this.dataFromBase64(base64)
    let hexHeader = this.hexHeaderFromData(data)
    let fileType = this.getFileTypeFromhexHeader(hexHeader)
    return fileType
  } catch (error) {
    this.addErrorLog(error, "getFileTypeFromBase64")
    return 'unknown';
  }
}
/**
 * 
 * @param {string} hexHeader 
 * @returns 
 */
static getFileTypeFromhexHeader(hexHeader) {
  try {
      const fileTypes = {
      'FFD8FF': 'jpg',          // JPG/JPEG
      '89504E47': 'png',        // PNG
      '47494638': 'gif',        // GIF
      '25504446': 'pdf',        // PDF
      '504B0304': 'zip',        // ZIP（包括 docx、xlsx 等）
      '7B5C727466': 'rtf',      // RTF
      '4D5A': 'exe',            // EXE/DLL
      '494433': 'mp3',          // MP3
      '0000001466747970': 'mp4',// MP4
    };

    // 从长前缀到短前缀匹配（避免误判）
    const sortedTypes = Object.entries(fileTypes).sort(([a], [b]) => b.length - a.length);
    for (const [hexPrefix, type] of sortedTypes) {
      if (hexHeader.startsWith(hexPrefix)) {
        return type;
      }
    }
    return 'unknown';
  } catch (error) {
    this.addErrorLog(error, "getFileTypeFromhexHeader")
    return 'unknown';
  }
}
/**
 * 
 * @param {NSData} data 
 * @returns {string} 文件格式（如 'jpg', 'png', 'pdf' 等，未知则返回 'unknown'）
 */
static getFileTypeFromData(data) {
  try {
    let hexHeader = this.hexHeaderFromData(data)
    let fileType = this.getFileTypeFromhexHeader(hexHeader)
    return fileType
  } catch (error) {
    this.addErrorLog(error, "getFileTypeFromData")
    return 'unknown'
  }
}
/**
 * 
 * @param {NSData|string} data 
 */
static getFileType(data){
  if (data instanceof NSData) {
    return this.getFileTypeFromData(data)
  }
  if (typeof data === "string") {
    if (data.startsWith("data:")) {
      return this.fileTypeFromBase64URL(data)
    }else{
      //单纯的base64字符串，无法直接判断格式
      return this.getFileTypeFromBase64(data)
    }
  }
  return 'unknown'
}

/**
 * 1. 健壮的 Base64 解码器
 * - 自动处理带前缀/不带前缀的情况
 * - 自动去除换行符、空格 (JSBridge 返回的数据常带有换行)
 * - 不依赖 atob
 * @param {string} base64Str 
 * @returns {Uint8Array}
 */
static base64ToUint8Array(base64Str) {
  // 1. 彻底清洗数据：去除 "data:image/xxx;base64," 前缀，去除所有空格和换行
  let cleanStr = base64Str;
  if (cleanStr.includes(',')) {
    cleanStr = cleanStr.split(',')[1];
  }
  cleanStr = cleanStr.replace(/[\s\r\n]+/g, '');
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  // 使用对象作为 lookup table 会比数组更安全一些
  const lookup = new Uint8Array(256);
  for (let i = 0; i < chars.length; i++) {
    lookup[chars.charCodeAt(i)] = i;
  }
  const len = cleanStr.length;
  let bufferLength = len * 0.75;
  if (cleanStr[len - 1] === '=') {
    bufferLength--;
    if (cleanStr[len - 2] === '=') {
      bufferLength--;
    }
  }
  const array = new Uint8Array(bufferLength);
  let p = 0;
  for (let i = 0; i < len; i += 4) {
    const encoded1 = lookup[cleanStr.charCodeAt(i)];
    const encoded2 = lookup[cleanStr.charCodeAt(i + 1)];
    const encoded3 = lookup[cleanStr.charCodeAt(i + 2)];
    const encoded4 = lookup[cleanStr.charCodeAt(i + 3)];
    array[p++] = (encoded1 << 2) | (encoded2 >> 4);
    if (encoded3 !== 64 && p < bufferLength) array[p++] = ((encoded2 & 15) << 4) | (encoded3 >> 2);
    if (encoded4 !== 64 && p < bufferLength) array[p++] = ((encoded3 & 3) << 6) | (encoded4 & 63);
  }
  return array;
}

/**
 * 健壮的 Base64 解码器
 * - 自动去除换行符、空格 (JSBridge 返回的数据常带有换行)
 * - 不依赖 atob
 * @param {NSData} data 
 * @returns {Uint8Array}
 */
static NSDataToUint8Array(data) {
  // 1. 彻底清洗数据：去除 "data:image/xxx;base64," 前缀，去除所有空格和换行
  let cleanStr = data.base64Encoding();
  cleanStr = cleanStr.replace(/[\s\r\n]+/g, '');
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  // 使用对象作为 lookup table 会比数组更安全一些
  const lookup = new Uint8Array(256);
  for (let i = 0; i < chars.length; i++) {
    lookup[chars.charCodeAt(i)] = i;
  }
  const len = cleanStr.length;
  let bufferLength = len * 0.75;
  if (cleanStr[len - 1] === '=') {
    bufferLength--;
    if (cleanStr[len - 2] === '=') {
      bufferLength--;
    }
  }
  const array = new Uint8Array(bufferLength);
  let p = 0;
  for (let i = 0; i < len; i += 4) {
    const encoded1 = lookup[cleanStr.charCodeAt(i)];
    const encoded2 = lookup[cleanStr.charCodeAt(i + 1)];
    const encoded3 = lookup[cleanStr.charCodeAt(i + 2)];
    const encoded4 = lookup[cleanStr.charCodeAt(i + 3)];
    array[p++] = (encoded1 << 2) | (encoded2 >> 4);
    if (encoded3 !== 64 && p < bufferLength) array[p++] = ((encoded2 & 15) << 4) | (encoded3 >> 2);
    if (encoded4 !== 64 && p < bufferLength) array[p++] = ((encoded3 & 3) << 6) | (encoded4 & 63);
  }
  return array;
}
/**
 * Uint8Array/ArrayBuffer/普通数组 转 Base64 字符串
 * - 无依赖，不使用 btoa
 * - 高性能：查找表 + 批量处理
 * - 支持输入：Uint8Array、ArrayBuffer、number[]
 * - 自动补位（处理长度不是 3 的倍数的情况）
 */
static uint8ArrayToBase64(input) {
  // 1. 统一输入为 Uint8Array（兼容多种输入类型）
  let uint8;
  if (input instanceof Uint8Array) {
    uint8 = input;
  } else if (input instanceof ArrayBuffer) {
    uint8 = new Uint8Array(input);
  } else if (Array.isArray(input)) {
    // 过滤非数字/超出 0-255 范围的元素（健壮性处理）
    uint8 = new Uint8Array(input.filter(n => typeof n === 'number' && n >= 0 && n <= 255));
  } else {
    throw new Error('Unsupported input type. Expected Uint8Array, ArrayBuffer, or number[].');
  }

  // 2. 预生成 Base64 字符查找表（64 个字符）
  const base64Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const lookup = base64Chars.split(''); // 索引 0→'A', 1→'B', ..., 63→'/'

  const len = uint8.length;
  let base64Str = '';
  let i = 0;

  // 3. 批量处理：每 3 个字节转 4 个 Base64 字符（核心优化）
  while (i < len) {
    // 取当前 3 个字节（不足则补 0）
    const byte1 = uint8[i++] || 0;
    const byte2 = uint8[i++] || 0;
    const byte3 = uint8[i++] || 0;

    // 计算 4 个 Base64 字符的索引（3 字节 → 24 位 → 拆分为 4 个 6 位）
    const index1 = (byte1 >> 2) & 0x3F; // 前 6 位
    const index2 = ((byte1 & 0x03) << 4) | (byte2 >> 4); // 后 2 位 + 中间 4 位
    const index3 = ((byte2 & 0x0F) << 2) | (byte3 >> 6); // 中间 4 位 + 后 2 位
    const index4 = byte3 & 0x3F; // 最后 6 位

    // 根据输入长度补位（长度不是 3 的倍数时，末尾补 '='）
    const char3 = (i > len + 1) ? '=' : lookup[index3]; // 少 2 个字节 → 补 2 个 '='
    const char4 = (i > len) ? '=' : lookup[index4];       // 少 1 个字节 → 补 1 个 '='

    // 拼接当前 4 个字符
    base64Str += lookup[index1] + lookup[index2] + char3 + char4;
  }

  return base64Str;
}

  /**
   * 在纯 JavaScript 中更改 PNG 图片的颜色，不使用 Canvas 或 Buffer。
   * 此方法通过修改 PNG 的 PLTE (调色板) 数据块来实现。
   * 它仅适用于使用调色板的索引色 PNG 图片。
   *
   * @param {Uint8Array} bytes 原始 PNG 图片的 Uint8Array。
   * @param {string} hexColor 目标颜色的十六进制字符串 (例如, '#FF0000')。
   * @param {Array<number>} [sourceRgb=[255, 255, 255]] 要被替换的源颜色RGB数组，默认为白色。
   * @returns {string|null} 返回一个新的带 'data:image/png;base64,' 前缀的 Base64 字符串，如果失败则返回 null。
   */
  static changePngColor(bytes, hexColor, sourceRgb = [255, 255, 255]) {
  try {

    /**
     * 计算 PNG 块的 CRC-32 校验和。
     * 这是一个标准的 CRC-32 实现。
     */
    const crc32 = (function() {
        const table = new Uint32Array(256);
        for (let i = 0; i < 256; i++) {
            let c = i;
            for (let k = 0; k < 8; k++) {
                c = ((c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1));
            }
            table[i] = c;
        }
        return function(bytes) {
            let crc = -1;
            for (let i = 0; i < bytes.length; i++) {
                crc = (crc >>> 8) ^ table[(crc ^ bytes[i]) & 0xFF];
            }
            return (crc ^ -1) >>> 0;
        };
    })();
        // 2. 验证 PNG 文件签名
        const pngSignature = [137, 80, 78, 71, 13, 10, 26, 10];
        for (let i = 0; i < pngSignature.length; i++) {
            if (bytes[i] !== pngSignature[i]) {
                return null;
            }
        }
        const newRgb = this.hexToRgb(hexColor);
        let foundPlte = false;

        // 3. 遍历 PNG 的数据块
        let i = 8; // 从第一个块开始 (跳过8字节的文件签名)
        while (i < bytes.length) {
            // 使用 DataView 来方便地读取大端序的32位整数
            const view = new DataView(bytes.buffer);
            const length = view.getUint32(i, false); // 块数据的长度
            const type = String.fromCharCode(bytes[i + 4], bytes[i + 5], bytes[i + 6], bytes[i + 7]); // 块类型

            const chunkDataStart = i + 8;
            const chunkDataEnd = chunkDataStart + length;
            const crcStart = chunkDataEnd;

            // 4. 找到并修改 PLTE (调色板) 块
            if (type === 'PLTE') {
                foundPlte = true;
                // 遍历调色板中的颜色 (每种颜色3个字节: R, G, B)
                for (let p = chunkDataStart; p < chunkDataEnd; p += 3) {
                    const r = bytes[p];
                    const g = bytes[p + 1];
                    const b = bytes[p + 2];

                    // 如果找到源颜色 (默认为白色)，就替换为新颜色
                    if (r === sourceRgb[0] && g === sourceRgb[1] && b === sourceRgb[2]) {
                    //     console.log("找到源颜色，替换为新颜色")
                        
                        bytes[p] = newRgb[0];
                        bytes[p + 1] = newRgb[1];
                        bytes[p + 2] = newRgb[2];
                    }
                }

                // 5. 重新计算修改后块的 CRC 校验和
                // CRC 的计算范围是块类型和块数据
                const chunkTypeAndData = bytes.subarray(i + 4, chunkDataEnd);
                const newCrc = crc32(chunkTypeAndData);
                view.setUint32(crcStart, newCrc, false); // 将新的 CRC 写回
            }

            if (type === 'IEND') {
                break; // 到达文件末尾
            }

            // 移动到下一个块的起始位置
            i = crcStart + 4;
        }

        if (!foundPlte) {
            return null;
        }

        // 6. 将修改后的字节数组重新编码为 Base64 字符串
        // let newBinaryString = '';
        // bytes.forEach(byte => {
        //     newBinaryString += String.fromCharCode(byte);
        // });
        // const newBase64 = btoa_crypto(newBinaryString);
        const newBase64 = DataConverter.uint8ArrayToBase64(bytes)
        return 'data:image/png;base64,' + newBase64;
  
} catch (error) {
  toolbarUtils.addErrorLog(error, "changePngColor")
  return null
}
}
static getDotBase64WithColor(hexColor) {
  let bytes = MNUtil.dotBytes
  let newBase64 = this.changePngColor(bytes, hexColor)
  return newBase64
}
static getDotImageWithColor(hexColor) {
  let base64 = this.getDotBase64WithColor(hexColor)
  let image = this.imageFromBase64(base64)
  return image
}
}
