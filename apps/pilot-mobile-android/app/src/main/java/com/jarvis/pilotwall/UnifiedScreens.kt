package com.jarvis.pilotwall

import androidx.compose.runtime.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.LocalActivity
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.*
import org.json.*
import okhttp3.*
import java.util.UUID

@Composable fun ControlScreen(){
 val context=LocalContext.current;val client=remember{UnifiedClient(context)};val scope=rememberCoroutineScope()
 var pane by remember{mutableStateOf("Chat")};var target by remember{mutableStateOf("auto")};var project by remember{mutableStateOf("")};var text by remember{mutableStateOf("")};var status by remember{mutableStateOf("")};var busy by remember{mutableStateOf(false)}
 var projects by remember{mutableStateOf<List<JSONObject>>(emptyList())};var tasks by remember{mutableStateOf<List<JSONObject>>(emptyList())};var workers by remember{mutableStateOf<List<JSONObject>>(emptyList())};var conversations by remember{mutableStateOf<List<JSONObject>>(emptyList())};var detail by remember{mutableStateOf<JSONObject?>(null)}
 val messages=remember{mutableStateMapOf<String,String>()};val approvals=remember{mutableStateListOf<JSONObject>()};var approve by remember{mutableStateOf<JSONObject?>(null)}
 suspend fun refresh(){withContext(Dispatchers.IO){val p=(client.control("/v1/projects") as JSONArray).objects();val t=(client.control("/v1/tasks") as JSONArray).objects();val w=(client.control("/v1/workers") as JSONArray).objects();val c=(client.control("/v1/conversations") as JSONObject).arr("data").objects();withContext(Dispatchers.Main){projects=p;tasks=t;workers=w;conversations=c}}}
 fun run(block:suspend()->Unit){scope.launch{busy=true;try{block();status=""}catch(e:Exception){status=e.message?:"Connection unavailable"}finally{busy=false}}}
 LaunchedEffect(Unit){try{refresh()}catch(e:Exception){status=e.message?:"James Control unavailable"}}
 DisposableEffect(Unit){val socket=client.controlEvents(object:WebSocketListener(){override fun onMessage(ws:WebSocket,data:String){scope.launch{runCatching{val e=JSONObject(data);when(e.s("type")){"message.delta"->messages[e.s("id")]=(messages[e.s("id")]?:"")+e.s("text");"message.completed"->messages[e.s("id")]=e.s("text");"approval.requested"->{val a=e.obj("approval");if(approvals.none{it.s("id")==a.s("id")})approvals.add(a)};"task.updated","worker.updated"->refresh()}}}};override fun onFailure(ws:WebSocket,t:Throwable,response:Response?){scope.launch{status="Live connection interrupted. Refresh to reconnect."}}});onDispose{socket.close(1000,"Screen closed")}}
 LazyColumn(contentPadding=PaddingValues(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp),modifier=Modifier.fillMaxSize()){
 item{Head("James Control","Projects, workers and conversations");Row(Modifier.horizontalScroll(rememberScrollState())){listOf("Chat","Projects","Tasks","Workers","Conversations").forEach{p->FilterChip(selected=pane==p,onClick={pane=p},label={Text(p)})}};if(status.isNotBlank())Text(status,color=MaterialTheme.colorScheme.error);TextButton(onClick={run{refresh()}},enabled=!busy){Text("Refresh")}}
 when(pane){
 "Chat"->{items(messages.toList()){(id,body)->Tile(tasks.find{it.s("id")==id}?.s("title")?:"Conversation"){Text(body)}};items(approvals){a->Tile("Approval requested",a.s("title")){Text(a.s("detail"));TextButton(onClick={approve=a}){Text("Review request")}}};item{Row{listOf("auto","codex","hermes").forEach{t->FilterChip(selected=target==t,onClick={target=t},label={Text(label(t))})}}};item{Row(Modifier.horizontalScroll(rememberScrollState())){FilterChip(selected=project.isBlank(),onClick={project=""},label={Text("Automatic project")});projects.forEach{p->FilterChip(selected=project==p.s("id"),onClick={project=p.s("id")},label={Text(p.s("name"))})}}};item{OutlinedTextField(text,{text=it},label={Text("Message James Control")},modifier=Modifier.fillMaxWidth());Button(enabled=!busy&&text.isNotBlank(),onClick={val draft=text;val request=json("text" to draft,"target" to target,"idempotency_key" to UUID.randomUUID().toString());if(project.isNotBlank())request.put("project_id",project);run{withContext(Dispatchers.IO){client.control("/v1/messages","POST",request)};text="";refresh()}}){Text("Send")}}}
 "Projects"->items(projects){p->Tile(p.s("name"),"${p.s("sync_state")} · ${p.s("build_state")}"){Text(p.s("host"));TextButton(onClick={project=p.s("id");pane="Chat"}){Text("Open project chat")}}}
 "Tasks"->items(tasks){t->Tile(t.s("title"),"${t.s("status")} · ${t.s("host")}"){Text(t.s("progress"));TextButton(onClick={run{val events=withContext(Dispatchers.IO){client.control("/v1/tasks/${t.s("id")}/events")};detail=json("events" to events)}}){Text("View activity")}}}
 "Workers"->items(workers){w->Tile(w.s("name"),"${w.s("platform")} · ${w.s("status")}"){Text(w.s("current_task"))}}
 else->items(conversations){c->Tile(c.s("title"),c.s("updated_at")){Text(c.s("preview"));TextButton(onClick={run{detail=withContext(Dispatchers.IO){client.control("/v1/conversations/${c.s("id")}?host_id=${android.net.Uri.encode(c.s("host_id"))}") as JSONObject}}}){Text("Read conversation")}}}
 }
 }
 detail?.let{d->AlertDialog(onDismissRequest={detail=null},title={Text("Activity")},text={Column(Modifier.verticalScroll(rememberScrollState())){Detail(d)}},confirmButton={TextButton(onClick={detail=null}){Text("Close")}})}
 approve?.let{a->AlertDialog(onDismissRequest={approve=null},title={Text(a.s("title"))},text={Text(a.s("detail"))},confirmButton={TextButton(enabled=!busy,onClick={run{withContext(Dispatchers.IO){client.control("/v1/approvals/${a.s("id")}","POST",json("decision" to "accept"))};approvals.removeAll{it.s("id")==a.s("id")};approve=null}}){Text("Approve")}},dismissButton={TextButton(enabled=!busy,onClick={run{withContext(Dispatchers.IO){client.control("/v1/approvals/${a.s("id")}","POST",json("decision" to "decline"))};approvals.removeAll{it.s("id")==a.s("id")};approve=null}}){Text("Decline")}})}
}

@Composable fun EnergyManagerScreen(){
 val context=LocalContext.current;val activity=LocalActivity.current!!;val client=remember{UnifiedClient(context)};val scope=rememberCoroutineScope()
 var data by remember{mutableStateOf(JSONObject())};var history by remember{mutableStateOf<List<JSONObject>>(emptyList())};var daily by remember{mutableStateOf<List<JSONObject>>(emptyList())};var pane by remember{mutableStateOf("Overview")};var busy by remember{mutableStateOf(false)};var status by remember{mutableStateOf("")};var pending by remember{mutableStateOf<String?>(null)};var editing by remember{mutableStateOf(false)}
 suspend fun refresh(){val value=withContext(Dispatchers.IO){client.energy("/mobile/v1/bootstrap") as JSONObject};data=value;history=withContext(Dispatchers.IO){(client.energy("/mobile/v1/history?limit=288") as JSONArray).objects()};daily=withContext(Dispatchers.IO){(client.energy("/mobile/v1/daily?limit=30") as JSONArray).objects()}}
 fun run(block:suspend()->Unit){scope.launch{busy=true;status="";try{block()}catch(e:Exception){status=e.message?:"Energy manager unavailable"}finally{busy=false}}}
 LaunchedEffect(Unit){(client.cached("energy","/mobile/v1/bootstrap") as? JSONObject)?.let{data=it;status="Saved on this phone · updating…"};while(true){try{refresh();status=if(client.offline)"Offline · saved ${client.savedAt?:"previous session"}" else "Live"}catch(e:Exception){status="Updates unavailable · ${e.message}"};delay(15_000)}}
 LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
 item{Head("House Energy",status);Row(Modifier.horizontalScroll(rememberScrollState())){listOf("Overview","Plan","History","Daily","Controls").forEach{p->FilterChip(selected=pane==p,onClick={pane=p},label={Text(p)})}}}
 when(pane){
 "Overview"->houseOverview(data)
 "Plan"->housePlan(data)
 "History"->item{EnergyChart("Energy history",history.map{it.optJSONObject("telemetry")?:it},listOf(Triple("pv_kw","Solar",PilotAmber),Triple("load_kw","Home",PilotCyan),Triple("grid_kw","Grid",PilotMint))) }
 "Daily"->items(daily){d->EnergyCard{Text(d.s("date",d.s("day","Daily totals")));EnergyValue("Generated",d.measure("solar_generated_kwh","kWh"),PilotAmber);EnergyValue("Home used",d.measure("house_consumed_kwh","kWh"),PilotCyan);EnergyValue("Exported",d.measure("grid_exported_kwh","kWh"),PilotMint)}}
 else->{item{Tile("EV and energy settings"){val settings=data.obj("settings");Text("EV charge limit: ${settings.s("ev_charge_limit_pct")} %");Text("Minimum sell price: ${settings.s("min_sell_price_per_kwh")} / kWh");Text("Trip: ${label(settings.s("ev_trip_profile"))}");Text("Grid charging: ${if(settings.optBoolean("ev_grid_allowed"))"Allowed"else "Off"}");Button(onClick={editing=true},enabled=!busy&&data.has("settings_revision")){Text("Edit settings")}}};items(listOf("enable-automation","disable-automation","hot-water-enable","hot-water-away","stop-ev","stop-hot-water","safe-state")){a->OutlinedButton(enabled=!busy,onClick={pending=a},modifier=Modifier.fillMaxWidth()){Text(label(a.replace('-',' ')))}}}
 }
 }
 if(editing){val s=data.obj("settings");EditDialog("Energy settings",listOf(Field("charge","EV charge limit %",s.s("ev_charge_limit_pct","80"),true),Field("sell","Minimum sell price / kWh",s.s("min_sell_price_per_kwh","0.10"),true),Field("fit","Opportunity ceiling / kWh",s.s("ev_opportunistic_fit_max_per_kwh","0.01"),true),Field("grid","Grid charging: true or false",s.s("ev_grid_allowed","false")),Field("trip","Trip profile",s.s("ev_trip_profile","no_trip"))),busy,status.takeIf{it!="Live"},{editing=false}){v->run{val charge=v["charge"]!!.toInt();require(charge in 50..100){"Charge limit must be 50–100%"};require(v["grid"] in listOf("true","false"));val body=json("ev_charge_limit_pct" to charge,"min_sell_price_per_kwh" to v["sell"]!!.toDouble(),"ev_opportunistic_fit_max_per_kwh" to v["fit"]!!.toDouble(),"ev_grid_allowed" to v["grid"].toBoolean(),"ev_trip_profile" to v["trip"]);withContext(Dispatchers.IO){client.energy("/mobile/v1/settings","PATCH",body,mapOf("If-Match" to data.s("settings_revision")))};editing=false;refresh()}}}
 pending?.let{a->AlertDialog(onDismissRequest={pending=null},title={Text("Confirm ${a.replace('-',' ')}")},text={Text("Authenticate on this phone to authorize this command. The energy manager will confirm the result.")},confirmButton={TextButton(enabled=!busy,onClick={run{val result=client.safeAction(activity,a);pending=null;refresh();status="Command confirmed: $result"}}){Text("Authenticate and send")}},dismissButton={TextButton(onClick={pending=null},enabled=!busy){Text("Cancel")}})}
}
