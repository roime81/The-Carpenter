(() => {
  const svg = document.getElementById("infrastructure-graph");
  if (!svg) return;
  const NS = "http://www.w3.org/2000/svg";
  const meshLayer = document.getElementById("graph-mesh");
  const edgesLayer = document.getElementById("graph-edges");
  const nodesLayer = document.getElementById("graph-nodes");
  const hint = document.getElementById("canvas-hint");
  const summary = document.getElementById("graph-summary");
  const counter = document.getElementById("stream-counter");
  const streamState = document.getElementById("stream-state");
  const streamDot = document.getElementById("stream-dot");
  const inspectorTitle = document.getElementById("inspector-title");
  const inspectorStatus = document.getElementById("inspector-status");
  const inspectorDescription = document.getElementById("inspector-description");
  const inspectorFacts = document.getElementById("inspector-facts");
  const inspectorLogs = document.getElementById("inspector-logs");
  const timestamps = document.getElementById("node-timestamps");
  const toggleLabels = document.getElementById("toggle-labels");
  const eventList = document.getElementById("event-list");
  const eventCount = document.getElementById("event-count");
  const artifactState = document.getElementById("artifact-state");
  const artifactDialog = document.getElementById("artifact-dialog");
  const artifactDialogTitle = document.getElementById("artifact-dialog-title");
  const artifactDialogMeta = document.getElementById("artifact-dialog-meta");
  const artifactDialogContent = document.getElementById("artifact-dialog-content");

  let snapshot = {nodes:[], edges:[], events:[], artifacts:[]};
  let positions = new Map();
  let selectedId = "stage:root";
  let labelsVisible = true;
  let source = null;
  let fitted = false;

  const fixed = {
    "stage:root": [560, 310],
    "stage:intent": [560, 165],
    "stage:discovery": [315, 175],
    "stage:blueprint": [790, 160],
    "stage:playbook": [940, 315],
    "stage:functions": [805, 485],
    "stage:iac": [570, 500],
    "stage:approval": [390, 475],
    "stage:provision": [185, 405],
    "stage:verified": [155, 245]
  };
  const statusText = {
    idle:"DORMANT", ready:"READY", online:"ONLINE", observed:"OBSERVED", waiting:"WAITING", queued:"QUEUED",
    running:"RUNNING", started:"STARTED", succeeded:"SUCCEEDED", ready:"READY", reachable:"REACHABLE",
    applied:"APPLIED", mounted:"MOUNTED", available:"AVAILABLE", up:"UP", down:"DOWN", offline:"OFFLINE", failed:"FAILED"
  };
  const statusClass = value => ({
    idle:"idle", down:"idle", offline:"idle", ready:"ready", online:"ready", waiting:"waiting", observed:"waiting", queued:"queued",
    running:"active", reachable:"active", mounted:"active", succeeded:"done", started:"done", applied:"queued", available:"done", up:"ready", failed:"blocked"
  }[value] || "waiting");
  const fmtTime = value => {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, {dateStyle:"medium", timeStyle:"medium"}).format(date);
  };
  const shortId = value => value ? String(value).length > 18 ? String(value).slice(0,8)+"…"+String(value).slice(-5) : String(value) : "—";
  const make = (tag, attrs, parent) => {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key,value]) => el.setAttribute(key,String(value)));
    if (parent) parent.appendChild(el);
    return el;
  };
  const hash = value => {
    let h = 2166136261;
    for (let i=0;i<value.length;i++) { h ^= value.charCodeAt(i); h = Math.imul(h,16777619); }
    return h >>> 0;
  };
  const nodeRadius = node => {
    if (node.kind === "launcher") return 11;
    if (node.kind === "artifact") return 8;
    if (node.kind === "stage") return 7.5;
    if (node.kind === "worker") return Math.min(9,5+Math.log2((node.job_count||1)+1));
    if (node.kind === "topology") {
      const sizes={control_plane:13,cluster:11,compute_host:10,hypervisor_node:9,virtual_machine:8,workload:8,service:7,network:6.5,network_interface:5.5,storage_volume:6,hypervisor:7,container_runtime:5.8,namespace:5.5};
      return sizes[node.resource_type]||6;
    }
    if (node.kind === "resource") return 4.8;
    return 4.2;
  };
  const nodeName = node => node.label || node.id;
  const setLive = (state, ok) => {
    if (streamState) streamState.textContent = state;
    if (streamDot) streamDot.classList.toggle("offline", !ok);
  };
  function computePositions() {
    positions = new Map();
    const nodes = snapshot.nodes || [];
    const byId = new Map(nodes.map(node=>[node.id,node]));
    const childrenByParent = new Map();
    const incoming = new Map();
    (snapshot.edges||[]).forEach(edge=>{
      if(!incoming.has(edge.target)) incoming.set(edge.target,[]);
      incoming.get(edge.target).push(edge.source);
    });
    nodes.forEach(node=>{
      if (fixed[node.id]) positions.set(node.id,{x:fixed[node.id][0],y:fixed[node.id][1]});
    });
    const pending = nodes.filter(node=>!positions.has(node.id));
    let guard = pending.length + 2;
    while(pending.length && guard-- > 0) {
      for(let i=pending.length-1;i>=0;i--) {
        const node=pending[i];
        const parents=(incoming.get(node.id)||[]).map(id=>positions.get(id)).filter(Boolean);
        let anchor={x:560,y:310};
        if(parents.length) anchor={
          x:parents.reduce((sum,pos)=>sum+pos.x,0)/parents.length,
          y:parents.reduce((sum,pos)=>sum+pos.y,0)/parents.length
        };
        const bucket=node.parent_id || ((incoming.get(node.id)||[])[0]) || node.kind;
        const index=childrenByParent.get(bucket)||0;
        childrenByParent.set(bucket,index+1);
        const angle=((hash(node.id)%100000)/100000)*Math.PI*2 + index*2.399963;
        const base=node.kind==="worker"?78:node.kind==="job"?62:node.kind==="resource"?100:85;
        const radius=base + Math.sqrt(index)*24;
        let x=anchor.x+Math.cos(angle)*radius;
        let y=anchor.y+Math.sin(angle)*radius;
        x=Math.max(42,Math.min(1078,x)); y=Math.max(42,Math.min(578,y));
        positions.set(node.id,{x,y});
        pending.splice(i,1);
      }
    }
    // A fixed stable relaxation gives the cloud a natural network topology without
    // changing the location of existing nodes when the stream emits another snapshot.
    const movable=nodes.filter(node=>!fixed[node.id]);
    for(let step=0;step<34;step++) {
      const delta=new Map(movable.map(node=>[node.id,{x:0,y:0}]));
      for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++) {
        const a=nodes[i],b=nodes[j],pa=positions.get(a.id),pb=positions.get(b.id);
        if(!pa||!pb) continue;
        const dx=pa.x-pb.x,dy=pa.y-pb.y,d2=dx*dx+dy*dy;
        if(d2>170*170) continue;
        const distance=Math.max(1,Math.sqrt(d2));
        const force=(170-distance)*0.0032;
        const fx=dx/distance*force,fy=dy/distance*force;
        if(delta.has(a.id)){delta.get(a.id).x+=fx;delta.get(a.id).y+=fy;}
        if(delta.has(b.id)){delta.get(b.id).x-=fx;delta.get(b.id).y-=fy;}
      }
      (snapshot.edges||[]).forEach(edge=>{
        const pa=positions.get(edge.source),pb=positions.get(edge.target);
        if(!pa||!pb) return;
        const dx=pb.x-pa.x,dy=pb.y-pa.y,distance=Math.max(1,Math.hypot(dx,dy));
        const force=(distance-105)*0.0012;
        const fx=dx/distance*force,fy=dy/distance*force;
        if(delta.has(edge.source)){delta.get(edge.source).x+=fx;delta.get(edge.source).y+=fy;}
        if(delta.has(edge.target)){delta.get(edge.target).x-=fx;delta.get(edge.target).y-=fy;}
      });
      movable.forEach(node=>{
        const p=positions.get(node.id),d=delta.get(node.id);
        if(!p||!d) return;
        p.x=Math.max(34,Math.min(1086,p.x+d.x));
        p.y=Math.max(34,Math.min(586,p.y+d.y));
      });
    }
  }
  function fitNetwork() {
    const pts=[...positions.values()];
    if(!pts.length) return;
    const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
    const minX=Math.min(...xs)-70,maxX=Math.max(...xs)+70;
    const minY=Math.min(...ys)-65,maxY=Math.max(...ys)+65;
    const width=Math.max(500,maxX-minX),height=Math.max(360,maxY-minY);
    const scale=Math.min(1120/width,620/height,1.35);
    const viewWidth=1120/scale,viewHeight=620/scale;
    const cx=(minX+maxX)/2,cy=(minY+maxY)/2;
    svg.setAttribute("viewBox",`${cx-viewWidth/2} ${cy-viewHeight/2} ${viewWidth} ${viewHeight}`);
    fitted=true;
  }
  function render() {
    computePositions();
    meshLayer.replaceChildren();edgesLayer.replaceChildren();nodesLayer.replaceChildren();
    const nodes=snapshot.nodes||[],byId=new Map(nodes.map(node=>[node.id,node]));
    const topologyCount=nodes.filter(node=>node.kind==="topology").length;
    const explicit=new Set();
    (snapshot.edges||[]).forEach(edge=>{
      const key=[edge.source,edge.target].sort().join("|");explicit.add(key);
      const a=positions.get(edge.source),b=positions.get(edge.target);
      if(!a||!b) return;
      const midX=(a.x+b.x)/2,midY=(a.y+b.y)/2;
      const curve=hash(key)%31-15;
      const dx=b.x-a.x,dy=b.y-a.y,dist=Math.max(1,Math.hypot(dx,dy));
      const qx=midX-(dy/dist)*curve,qy=midY+(dx/dist)*curve;
      make("path",{d:`M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`,class:"graph-edge edge-"+(edge.kind||"dependency")},edgesLayer);
    });
    // Low-opacity nearest-neighbour strands give the network its mesh-like visual language.
    const meshSeen=new Set();
    nodes.forEach(node=>{
      const p=positions.get(node.id);if(!p)return;
      const near=nodes.filter(other=>other.id!==node.id).map(other=>{
        const q=positions.get(other.id);return {other,q,d:q?Math.hypot(q.x-p.x,q.y-p.y):Infinity};
      }).filter(item=>item.q).sort((a,b)=>a.d-b.d).slice(0,3);
      near.forEach(item=>{
        if(item.d>205)return;
        const key=[node.id,item.other.id].sort().join("|");
        if(meshSeen.has(key)||explicit.has(key))return;
        meshSeen.add(key);
        make("line",{x1:p.x,y1:p.y,x2:item.q.x,y2:item.q.y,class:"mesh-edge"},meshLayer);
      });
    });
    nodes.forEach(node=>{
      const p=positions.get(node.id);if(!p)return;
      const state=statusClass(node.status),radius=nodeRadius(node);
      const resourceClass=node.resource_type?" resource-"+String(node.resource_type).replace(/[^a-z0-9_-]/gi,"-"):"";
      const g=make("g",{class:"graph-node status-"+state+resourceClass+(node.id===selectedId?" selected":""),tabindex:"0",role:"button","aria-label":nodeName(node)+", "+(statusText[node.status]||node.status||"unknown"),"data-node":node.id},nodesLayer);
      const title=make("title",{},g);title.textContent=nodeName(node)+" · "+(statusText[node.status]||node.status||"unknown")+(node.worker_id?" · "+node.worker_id:"");
      if(node.status==="running")make("circle",{cx:p.x,cy:p.y,r:radius+7,class:"node-pulse"},g);
      make("circle",{cx:p.x,cy:p.y,r:radius+4,class:"node-halo"},g);
      make("circle",{cx:p.x,cy:p.y,r:radius,class:"node-core"},g);
      if(labelsVisible && (node.kind==="launcher"||node.kind==="stage"||node.kind==="artifact"||node.id===selectedId||(node.kind==="topology"&&topologyCount<=45&&["control_plane","cluster","compute_host","hypervisor_node","virtual_machine","workload","service","network","storage_volume"].includes(node.resource_type)))) {
        const onLeft=p.x>850,tx=p.x+(onLeft?-13:13),anchor=onLeft?"end":"start";
        const label=make("text",{x:tx,y:p.y-radius-7,"text-anchor":anchor,class:"node-label"},g);label.textContent=nodeName(node);
        if(node.kind==="worker"||node.kind==="job"||node.kind==="resource") label.style.fontSize="8px";
      }
      g.addEventListener("click",()=>selectNode(node.id));
      g.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();selectNode(node.id);}});
    });
    const count=nodes.length,jobs=nodes.filter(node=>node.kind==="job").length,workers=nodes.filter(node=>node.kind==="worker").length;
    const done=nodes.filter(node=>node.status==="succeeded").length,running=nodes.filter(node=>node.status==="running").length,failed=nodes.filter(node=>node.status==="failed").length;
    counter.textContent=count+" NODES";
    summary.textContent=`${count} connected nodes · ${jobs} jobs · ${workers} workers · ${running} running · ${done} succeeded · ${failed} failed`;
    hint.classList.toggle("hidden",count>1);
    if(!fitted) fitNetwork();
    if(!byId.has(selectedId)) selectedId=nodes[0]?.id||"stage:root";
    renderInspector();
  }
  function addFact(label,value) {
    const wrapper=document.createElement("div"),key=document.createElement("span"),val=document.createElement("strong");
    key.textContent=label;val.textContent=value||"—";wrapper.append(key,val);inspectorFacts.appendChild(wrapper);
  }
  function addLog(item) {
    const row=document.createElement("div"),time=document.createElement("time"),message=document.createElement("p");
    row.className="node-log-row";time.textContent=fmtTime(item.at);message.textContent=item.message||"Worker event";
    row.append(time,message);inspectorLogs.appendChild(row);
  }
  function renderInspector() {
    const node=(snapshot.nodes||[]).find(item=>item.id===selectedId);
    if(!node)return;
    inspectorTitle.textContent=nodeName(node);
    inspectorStatus.textContent=statusText[node.status]||String(node.status||"unknown").toUpperCase();
    inspectorStatus.className="status-pill "+statusClass(node.status);
    inspectorDescription.textContent=node.description||"Live node in the infrastructure network.";
    inspectorFacts.replaceChildren();
    addFact("NODE TYPE",node.kind);
    addFact("STATUS",statusText[node.status]||node.status);
    if(node.function_name)addFact("FUNCTION",node.function_name+"@"+(node.function_version||"?"));
    if(node.resource_type)addFact("RESOURCE TYPE",node.resource_type);
    if(node.provider)addFact("PROVIDER",node.provider);
    if(node.native_id)addFact("NATIVE ID",node.native_id);
    if(node.version!==undefined&&node.kind==="topology")addFact("OBSERVATION VERSION",String(node.version));
    if(node.deployment_id)addFact("DEPLOYMENT",shortId(node.deployment_id));
    if(node.worker_id)addFact("WORKER",node.worker_id);
    if(node.job_id)addFact("JOB ID",shortId(node.job_id));
    if(node.attempt!==undefined)addFact("ATTEMPT",node.attempt+"/"+node.max_attempts);
    if(node.job_count!==undefined)addFact("LINKED JOBS",String(node.job_count));
    if(node.resource_id)addFact("RESOURCE",node.resource_id);
    if(node.capabilities?.length)addFact("CAPABILITIES",node.capabilities.join(", "));
    if(node.properties&&typeof node.properties==="object"){
      Object.entries(node.properties).slice(0,12).forEach(([key,value])=>{
        if(value===null||value===undefined||typeof value==="object")return;
        addFact(key.replace(/_/g," ").toUpperCase(),String(value));
      });
    }
    timestamps.replaceChildren();
    [["CREATED",node.created_at],["STARTED",node.started_at],["UPDATED",node.updated_at],["COMPLETED",node.completed_at]].forEach(([label,value])=>{
      if(!value)return;const row=document.createElement("div"),k=document.createElement("span"),v=document.createElement("time");
      k.textContent=label;v.textContent=fmtTime(value);row.append(k,v);timestamps.appendChild(row);
    });
    inspectorLogs.replaceChildren();
    if(node.error)addLog({at:node.completed_at||node.updated_at,message:"Failure: "+node.error});
    (node.logs||[]).slice(-12).forEach(addLog);
    if(!(node.logs||[]).length&&!node.error){
      const empty=document.createElement("div");empty.className="subtle-empty";
      empty.textContent=node.kind==="job"?"No worker events recorded yet.":"Select a job node to inspect its event history.";
      inspectorLogs.appendChild(empty);
    }
  }
  function renderEvents() {
    const events=(snapshot.events||[]).slice(-14).reverse();
    eventCount.textContent=events.length+" recent events";
    eventList.replaceChildren();
    if(!events.length){
      const empty=document.createElement("div");empty.className="journal-empty";
      const icon=document.createElement("span");icon.className="journal-spark";icon.textContent="✳";
      const copy=document.createElement("div"),title=document.createElement("strong"),desc=document.createElement("small");
      title.textContent="Waiting for worker activity";desc.textContent="Queue, claim, success and failure events will appear here.";
      copy.append(title,desc);empty.append(icon,copy);eventList.appendChild(empty);return;
    }
    events.forEach(event=>{
      const row=document.createElement("article");row.className="event-row";
      const marker=document.createElement("i");marker.className="event-marker "+(event.event_type||"").split(".").pop();
      const copy=document.createElement("div"),message=document.createElement("p"),meta=document.createElement("small");
      message.textContent=event.message||event.event_type;
      meta.textContent=fmtTime(event.created_at)+" · "+(event.event_type||"event").toUpperCase();
      copy.append(message,meta);row.append(marker,copy);eventList.appendChild(row);
    });
  }
  function renderArtifacts() {
    const artifacts=new Map((snapshot.artifacts||[]).map(item=>[item.kind,item]));
    ["blueprint","playbook"].forEach(kind=>{
      const card=document.getElementById("artifact-"+kind),button=card?.querySelector("button"),time=document.getElementById(kind+"-time");
      const item=artifacts.get(kind);
      if(button)button.disabled=!item;
      if(time)time.textContent=item?"Generated "+fmtTime(item.generated_at):"Not generated";
    });
    artifactState.textContent=artifacts.size?artifacts.size+" persisted artifacts":"Waiting for a deployment plan";
    const name=document.getElementById("deployment-name");
    if(name&&snapshot.deployment_id)name.textContent="Deployment "+shortId(snapshot.deployment_id);
  }
  function renderUpdated() {
    const updated=document.getElementById("graph-updated");
    const twin=snapshot.digital_twin||{};
    if(updated)updated.textContent=(twin.resource_count||0)+" OBSERVED RESOURCES · "+(twin.relationship_count||0)+" RELATIONSHIPS";
  }
  let previousNodeIds = new Set();
  function acceptSnapshot(next) {
    if(!next||!Array.isArray(next.nodes))return;
    const nextIds=new Set(next.nodes.map(node=>node.id));
    const graphChanged=nextIds.size!==previousNodeIds.size||[...nextIds].some(id=>!previousNodeIds.has(id));
    snapshot=next;
    if(graphChanged) fitted=false;
    previousNodeIds=nextIds;
    render();renderEvents();renderArtifacts();renderUpdated();
    setLive("LIVE · WORKER EVENTS SYNCED",true);
  }
  async function showArtifact(kind) {
    try {
      const response=await fetch("/api/v1/canvas/artifacts/"+encodeURIComponent(kind),{credentials:"same-origin",headers:{"Accept":"application/json"}});
      if(!response.ok)throw new Error(response.status===404?"This artifact has not been generated yet.":"Artifact preview could not be loaded.");
      const artifact=await response.json();
      artifactDialogTitle.textContent=artifact.title||kind;
      artifactDialogMeta.textContent=(artifact.filename||"")+(artifact.generated_at?" · Generated "+fmtTime(artifact.generated_at):"");
      artifactDialogContent.textContent=artifact.content||JSON.stringify(artifact.steps||artifact,null,2);
      artifactDialog.hidden=false;document.body.classList.add("dialog-open");
    } catch(error) {
      artifactDialogTitle.textContent="Preview unavailable";
      artifactDialogMeta.textContent="";
      artifactDialogContent.textContent=error.message||"The preview could not be loaded.";
      artifactDialog.hidden=false;document.body.classList.add("dialog-open");
    }
  }
  function closeDialog() { artifactDialog.hidden=true;document.body.classList.remove("dialog-open"); }
  document.querySelectorAll("[data-artifact]").forEach(button=>button.addEventListener("click",()=>showArtifact(button.dataset.artifact)));
  document.querySelectorAll("[data-close-dialog]").forEach(button=>button.addEventListener("click",closeDialog));
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!artifactDialog.hidden)closeDialog();});
  toggleLabels?.addEventListener("click",()=>{
    labelsVisible=!labelsVisible;toggleLabels.textContent=labelsVisible?"Labels on":"Labels off";
    toggleLabels.setAttribute("aria-pressed",String(labelsVisible));render();
  });
  document.getElementById("fit-canvas")?.addEventListener("click",()=>{fitted=false;fitNetwork();});
  const form=document.getElementById("prompt-form");
  form?.addEventListener("submit",()=>{
    const button=form.querySelector("button");
    if(button){button.textContent="…";button.disabled=true;}
    setLive("PROMPT SUBMITTED · WAITING FOR AGENT",true);
  });
  const input=document.getElementById("message");
  input?.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();form?.requestSubmit();}});

  const loadInitial=async()=>{
    try {
      const response=await fetch("/api/v1/canvas/snapshot",{credentials:"same-origin"});
      if(response.ok)acceptSnapshot(await response.json());
    } catch(error) { setLive("RECONNECTING TO CONTROL PLANE",false); }
  };
  loadInitial();
  if(window.EventSource) {
    source=new EventSource("/api/v1/canvas/stream");
    source.addEventListener("snapshot",event=>{
      try{acceptSnapshot(JSON.parse(event.data));}
      catch(error){setLive("INVALID CANVAS EVENT · RECONNECTING",false);}
    });
    source.onopen=()=>setLive("LIVE · CONNECTED TO CONTROL PLANE",true);
    source.onerror=()=>setLive("RECONNECTING TO CONTROL PLANE",false);
  } else {
    setLive("LIVE POLLING FALLBACK",true);
    window.setInterval(loadInitial,2000);
  }
  render();
})();