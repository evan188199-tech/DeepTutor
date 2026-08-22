/**
 * 似乎用处不大,每个插件都有一个单独的路径
 * 
 */
class RuntimeAssets {
  static init(extensionPath) {
    this.extensionPath = extensionPath
  }

  static resolve(path = "") {
    if (!this.extensionPath) {
      throw new Error("RuntimeAssets.resolve called before Runtime.init")
    }
    if (!path) {
      return this.extensionPath
    }
    return `${this.extensionPath}/${path.replace(/^\/+/, "")}`
  }
}

class Runtime {
  static lifecycleHandlers = []
  static routeHandlers = {}
  static initialized = false

  static init(context) {
    this.extensionPath = context
    RuntimeAssets.init(context)
    this.initialized = true
    return this
  }

  static ensureInitialized() {
    if (!this.initialized) {
      throw new Error("Runtime.init must be called before using Runtime")
    }
  }

  static registerLifecycle(handler) {
    this.lifecycleHandlers.push(handler)
    return handler
  }

  static emitLifecycle(name, ...args) {
    return this.lifecycleHandlers.map(handler => {
      if (typeof handler[name] === "function") {
        return handler[name](...args)
      }
      return undefined
    })
  }

  static registerRoute(name, handler) {
    this.routeHandlers[name] = handler
    return handler
  }

  static handleRoute(name, ...args) {
    if (!(name in this.routeHandlers)) {
      throw new Error(`Runtime route not registered: ${name}`)
    }
    return this.routeHandlers[name](...args)
  }
}

Runtime.assets = RuntimeAssets
globalThis.Runtime = Runtime
