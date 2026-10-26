const {contextBridge,ipcRenderer}=require("electron");
const call=(ch,...a)=>ipcRenderer.invoke(ch,...a);
contextBridge.exposeInMainWorld("selfedit",{
  state:()=>call("se:state"),
  runCycle:(offline)=>call("se:run",!!offline),
  apply:(id)=>call("se:apply",String(id)),
  reject:(id)=>call("se:reject",String(id)),
  rollback:(id)=>call("se:rollback",String(id)),
  wish:(text)=>call("se:wish",String(text)),
  log:(ev,data)=>call("se:log",String(ev),data),
  builtins:(list)=>call("se:builtins",list),
  config:(k,v)=>call("se:config",String(k),v),
  setKey:(key)=>call("se:set-key",String(key)),
  clearKey:()=>call("se:clear-key"),
  onChange:(cb)=>{const h=()=>cb();ipcRenderer.on("se:changed",h);return()=>ipcRenderer.removeListener("se:changed",h)},
});
