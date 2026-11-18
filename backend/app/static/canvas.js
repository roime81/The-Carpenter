(() => {
  const svg = document.getElementById("infrastructure-graph");
  if (!svg) return;
  const NS = "http://www.w3.org/2000/svg";
  const edges = document.getElementById("graph-edges");
  const nodesLayer = document.getElementById("graph-nodes");
  const hint = document.getElementById("canvas-hint");
  const summary = document.getElementById("graph-summary");
  const inspectorTitle = document.getElementById("inspector-title");
  const inspectorStatus = document.getElementById("inspector-status");
  const inspectorDescription = document.getElementById("inspector-description");
  const inspectorFacts = document.getElementById("inspector-facts");
  const toggleLabels = document.getElementById("toggle-labels");
  const nodes = [
    {id:"root",label:"The Carpenter",sub:"AGENT LAUNCHER",x:150,y:310,r:12,kind:"Agent",role:"Orchestration root",description:"The origin point for every infrastructure journey. The agent receives your outcome and coordinates the work.",deps:"None"},
    {id:"intent",label:"Intent",sub:"UNDERSTAND",x:330,y:310,r:8,kind:"Requirement",role:"Outcome definition",description:"Interprets the requested cloud, platform or workload outcome and extracts bounded deployment intent.",deps:"The Carpenter"},
    {id:"discovery",label:"Discovery",sub:"ENVIRONMENT",x:510,y:165,r:9,kind:"Discovery",role:"Read-only inventory",description:"Inspects enrolled and authorised workers, provider capabilities, capacity and available infrastructure.",deps:"Intent"},
    {id:"blueprint",label:"Blueprint",sub:"WORKBOOK",x:510,y:310,r:9,kind:"Design artifact",role:"Infrastructure design",description:"Represents the target architecture and the decisions needed to satisfy the requested outcome. The visual node is a workflow view, not a claim that a separate workbook file has been persisted.",deps:"Intent · Discovery"},
    {id:"playbook",label:"Playbook",sub:"EXECUTION PLAN",x:510,y:455,r:9,kind:"Execution plan",role:"Ordered operations",description:"Organises the intended build into reviewable operations, prerequisites and dependency order.",deps:"Blueprint"},
    {id:"functions",label:"Native functions",sub:"VERSIONED FaaS",x:720,y:165,r:9,kind:"Function catalogue",role:"Provider capabilities",description:"Selects registered, version-matched Python functions for the target provider. Workers execute allow-listed handlers only.",deps:"Discovery · Blueprint"},
    {id:"iac",label:"IaC resource graph",sub:"COMPILE + VALIDATE",x:720,y:310,r:10,kind:"IaC bundle",role:"Deterministic compiler",description:"Compiles the approved intent into a deterministic resource graph and provider artifacts, then validates allow-listed resource kinds and fingerprints.",deps:"Blueprint · Native functions"},
    {id:"approval",label:"Approval",sub:"HUMAN CONTROL",x:720,y:455,r:9,kind:"Policy gate",role:"Explicit authorisation",description:"A required human approval boundary. The model cannot approve itself or bypass readiness checks.",deps:"IaC resource graph"},
    {id:"provision",label:"Provisioning",sub:"DISTRIBUTED WORKERS",x:940,y:310,r:10,kind:"Execution",role:"Provider operations",description:"Queues versioned provider functions on selected data-plane workers. Queued work is not treated as completed infrastructure.",deps:"Approval · Native functions"},
    {id:"verify",label:"Verified cloud",sub:"RECONCILE",x:1060,y:455,r:9,kind:"Outcome",role:"Observed result",description:"Reconciles worker outcomes and reports the actual deployment state. A deployment is complete only when linked jobs succeed.",deps:"Provisioning"}
  ];
  const links = [["root","intent"],["intent","discovery"],["intent","blueprint"],["blueprint","playbook"],["discovery","functions"],["blueprint","iac"],["functions","iac"],["playbook","approval"],["iac","approval"],["functions","provision"],["approval","provision"],["provision","verify"]];
  const statusOrder = ["root","intent","discovery","blueprint","playbook","functions","iac","approval","provision","verify"];
  const states = Object.fromEntries(nodes.map(n=>[n.id,"idle"]));
  states.root = "root";
  let selected = "root";
  let labelsVisible = true;
  const make = (tag, attrs, parent) => { const el=document.createElementNS(NS,tag); Object.entries(attrs||{}).forEach(([k,v])=>el.setAttribute(k,v)); if(parent) parent.appendChild(el); return el; };
  const nodeMap = Object.fromEntries(nodes.map(n=>[n.id,n]));
  function selectNode(id){
    selected=id; const n=nodeMap[id], s=states[id];
    inspectorTitle.textContent=n.label;
    inspectorStatus.textContent=s==="done"?"COMPLETE":s==="active"?"IN PROGRESS":s==="blocked"?"ATTENTION":s==="root"?"READY":"DORMANT";
    inspectorStatus.className="status-pill "+(s==="done"?"done":s==="active"?"active":s==="blocked"?"blocked":"idle");
    inspectorDescription.textContent=n.description;
    inspectorFacts.innerHTML="";
    [["TYPE",n.kind],["ROLE",n.role],["DEPENDS ON",n.deps]].forEach(([k,v])=>{const d=document.createElement("div"),a=document.createElement("span"),b=document.createElement("strong");a.textContent=k;b.textContent=v;d.append(a,b);inspectorFacts.appendChild(d);});
    render();
  }
  function render(){
    edges.innerHTML=""; nodesLayer.innerHTML="";
    links.forEach(([a,b])=>{const na=nodeMap[a],nb=nodeMap[b],sa=states[a],sb=states[b];let status=sb==="done"?"done":sb==="active"?"active":"";make("path",{d:`M ${na.x} ${na.y} C ${(na.x+nb.x)/2} ${na.y}, ${(na.x+nb.x)/2} ${nb.y}, ${nb.x} ${nb.y}`,class:"graph-edge "+status},edges);});
    nodes.forEach(n=>{
      const s=states[n.id],g=make("g",{class:"graph-node status-"+s,tabindex:"0",role:"button","aria-label":n.label+", "+s,"data-node":n.id},nodesLayer);
      make("circle",{cx:n.x,cy:n.y,r:n.r+8,class:"node-pulse"},g);
      make("circle",{cx:n.x,cy:n.y,r:n.r+4,class:"node-halo",stroke:s==="done"?"#82e2c6":s==="active"?"#85baff":"#657181"},g);
      make("circle",{cx:n.x,cy:n.y,r:n.r,class:"node-core"},g);
      const tx= n.x+ (n.id==="root"?-17: n.id==="verify"?-8:15);
      const anchor=n.id==="root"?"end":n.id==="verify"?"end":"start";
      const label=make("text",{x:tx,y:n.y-13,"text-anchor":anchor,class:"node-label"},g);label.textContent=n.label;
      const sub=make("text",{x:tx,y:n.y+22,"text-anchor":anchor,class:"node-sub"},g);sub.textContent=n.sub;
      if(!labelsVisible){label.style.opacity="0";sub.style.opacity="0";}
      if(n.id===selected)make("circle",{cx:n.x,cy:n.y,r:n.r+13,fill:"none",stroke:"rgba(220,239,248,.7)","stroke-width":"1","stroke-dasharray":"2 4"},g);
      g.addEventListener("click",()=>selectNode(n.id));g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectNode(n.id);}});
    });
    const active=nodes.filter(n=>states[n.id]==="active").length,done=nodes.filter(n=>states[n.id]==="done").length;
    summary.textContent=`${done+1} nodes active in journey · ${done} complete · ${active} in progress`;
  }
  function applyConversationState(){
    const entries=[...document.querySelectorAll(".journal-entry")].map(e=>e.innerText.toLowerCase()).join(" ");
    const body=document.body.innerText.toLowerCase();
    const text=entries+" "+body;
    const hasPrompt=document.querySelectorAll(".journal-entry.user").length>0;
    if(!hasPrompt)return;
    ["intent","discovery","blueprint","playbook","functions","iac"].forEach(id=>states[id]="done");
    if(/discov|inventory|worker|capacity/.test(text))states.discovery="done";
    if(/blueprint|design|workbook|architecture/.test(text))states.blueprint="done";
    if(/playbook|execution plan/.test(text))states.playbook="done";
    if(/function|faas|provider/.test(text))states.functions="done";
    if(/iac|fingerprint|resource graph|generated artifact/.test(text))states.iac="done";
    if(/approval not completed|not ready|blocker|failed|error/.test(text)){states.approval="blocked";states.provision="idle";}
    else if(/approved/.test(text)){states.approval="done";}
    if(/queued|provision|dispatch/.test(text)){states.approval="done";states.provision="active";}
    if(/deployment status: succeeded|all jobs succeeded|verified cloud/.test(text)){states.provision="done";states.verify="done";}
    else if(/deployment status: failed/.test(text)){states.provision="blocked";}
    hint.classList.add("hidden");render();
    const selectedNode=nodes.find(n=>states[n.id]==="active")||nodes.find(n=>states[n.id]==="blocked")||nodes.find(n=>states[n.id]==="done"&&n.id!=="root");
    if(selectedNode)selectNode(selectedNode.id);
  }
  document.getElementById("fit-canvas")?.addEventListener("click",()=>{svg.style.transform="scale(1)";svg.style.transformOrigin="center";});
  toggleLabels?.addEventListener("click",()=>{labelsVisible=!labelsVisible;toggleLabels.textContent=labelsVisible?"Labels on":"Labels off";toggleLabels.setAttribute("aria-pressed",String(labelsVisible));render();});
  const form=document.getElementById("prompt-form");
  form?.addEventListener("submit",()=>{const btn=form.querySelector("button");if(btn){btn.textContent="…";btn.disabled=true;}const hintText=document.querySelector(".canvas-empty-hint small");if(hintText)hintText.textContent="Your instruction has been sent. The canvas will reflect the saved conversation when the agent responds.";});
  const input=document.getElementById("message");
  input?.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();form?.requestSubmit();}});
  render();applyConversationState();
})();