const {contextBridge,ipcRenderer,webUtils}=require("electron");
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

/* Reels Fabrikası köprüsü: yanıtlar {ok,data|error}; hata olursa Error fırlatılır. */
const fb=async(ch,...a)=>{const r=await ipcRenderer.invoke(ch,...a);if(!r||!r.ok)throw new Error((r&&r.error)||"fabrika hatası");return r.data};
contextBridge.exposeInMainWorld("fabrika",{
  status:()=>fb("fb:status"),
  start:()=>fb("fb:start"),
  get:(p)=>fb("fb:get",String(p)),
  post:(p,body)=>fb("fb:post",String(p),body||{}),
  uploadPath:(p)=>fb("fb:uploadPath",String(p)),
  uploadBuffer:(name,data)=>fb("fb:uploadBuffer",String(name),data),
  fetch:(rel)=>fb("fb:fetch",String(rel)),
  wait:(task)=>fb("fb:wait",String(task)),
  readFile:(p)=>fb("fb:readFile",String(p)),
  saveExport:(name,data,learn)=>fb("fb:saveExport",String(name),data,!!learn),
  show:(p)=>fb("fb:show",String(p)),
  pathOf:(file)=>{try{return webUtils&&webUtils.getPathForFile?webUtils.getPathForFile(file):(file&&file.path)||""}catch(e){return ""}},
});
