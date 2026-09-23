package com.jarvis.pilotwall
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.geometry.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import org.json.JSONObject
import kotlin.math.abs

@Composable fun EnergyCard(content:@Composable ColumnScope.()->Unit){Surface(Modifier.fillMaxWidth(),shape=RoundedCornerShape(20.dp),color=MaterialTheme.colorScheme.surface,border=BorderStroke(1.dp,MaterialTheme.colorScheme.onSurface.copy(alpha=.09f))){Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp),content=content)}}
fun JSONObject.measure(key:String,suffix:String="kW"):String=if(isNull(key))"—"else "%.1f %s".format(abs(optDouble(key)),suffix)
@Composable fun EnergyValue(title:String,value:String,tint:Color,modifier:Modifier=Modifier){Column(modifier,verticalArrangement=Arrangement.spacedBy(5.dp)){Text(title,fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant);Text(value,fontSize=19.sp,fontWeight=FontWeight.Bold,color=tint)}}
fun LazyListScope.houseOverview(data:JSONObject){val s=data.obj("snapshot");val t=s.obj("telemetry");val d=s.obj("devices");val daily=s.obj("daily_energy")
 item{EnergyCard{Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(16.dp)){Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(8.dp)){Text(label(s.obj("grid_health").s("state","Grid unknown")),color=PilotMint,fontWeight=FontWeight.SemiBold);Text(data.obj("plan").obj("rolling").obj("narrative").s("current_summary","Monitoring live energy flow"),fontSize=19.sp,fontWeight=FontWeight.SemiBold);val fit=s.obj("prices").obj("amber_fit");if(!fit.isNull("price_per_kwh"))Text("Feed-in now %.1fc/kWh".format(fit.optDouble("price_per_kwh")*100),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)};Box(Modifier.size(76.dp),contentAlignment=Alignment.Center){Canvas(Modifier.fillMaxSize()){drawCircle(PilotMint.copy(alpha=.12f),style=Stroke(8.dp.toPx()));drawArc(PilotMint,-90f,360*t.optDouble("soc_pct",0.0).toFloat().coerceIn(0f,100f)/100,false,style=Stroke(8.dp.toPx(),cap=StrokeCap.Round))};Text(if(t.isNull("soc_pct"))"—"else "${t.optInt("soc_pct")}%",fontWeight=FontWeight.Bold)}}}}
 item{EnergyCard{Text("WHOLE-SITE FLOW",fontSize=11.sp,color=MaterialTheme.colorScheme.onSurfaceVariant,letterSpacing=1.sp);Text("Power flow",fontSize=20.sp,fontWeight=FontWeight.Bold);HouseFlow(s)}}
 item{EnergyCard{Text("Today in Brisbane",fontWeight=FontWeight.SemiBold);Row(horizontalArrangement=Arrangement.spacedBy(12.dp)){EnergyValue("Generated",daily.measure("solar_generated_kwh","kWh"),PilotAmber,Modifier.weight(1f));EnergyValue("Home",daily.measure("house_consumed_kwh","kWh"),PilotCyan,Modifier.weight(1f));EnergyValue("Exported",daily.measure("grid_exported_kwh","kWh"),PilotMint,Modifier.weight(1f))}}}
 item{Row(horizontalArrangement=Arrangement.spacedBy(12.dp)){Box(Modifier.weight(1f)){EnergyCard{Text("Tesla",fontWeight=FontWeight.SemiBold);Text(if(d.isNull("ev_soc_pct"))"Away"else "${d.optInt("ev_soc_pct")}%",fontSize=26.sp,fontWeight=FontWeight.Bold);Text(if(d.optBoolean("ev_charging"))"Charging ${d.measure("ev_power_kw")}"else if(d.optBoolean("ev_plugged"))"Plugged in"else "Not charging",fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}};Box(Modifier.weight(1f)){EnergyCard{Text("Hot water",fontWeight=FontWeight.SemiBold);Text(if(d.optBoolean("hot_water_on"))"Heating"else "Ready",fontSize=26.sp,fontWeight=FontWeight.Bold);Text(d.measure("hot_water_power_kw"),fontSize=12.sp,color=MaterialTheme.colorScheme.onSurfaceVariant)}}}}
}
@Composable fun HouseFlow(s:JSONObject){val t=s.obj("telemetry");val d=s.obj("devices");val night=isSystemInDarkTheme();val car=d.optBoolean("ev_home");Box(Modifier.fillMaxWidth().height(320.dp)){
 Image(painterResource(if(night)if(car)R.drawable.house_night_car else R.drawable.house_night else if(car)R.drawable.house_day_car else R.drawable.house_day),"House energy flow",Modifier.fillMaxWidth().height(250.dp).align(Alignment.Center),contentScale=ContentScale.Fit)
 Image(painterResource(R.drawable.house_water),"Hot water tank",Modifier.size(45.dp,80.dp).align(Alignment.CenterStart))
 Image(painterResource(R.drawable.house_rack),"Server rack",Modifier.size(45.dp,80.dp).align(Alignment.CenterEnd))
 Column(Modifier.align(Alignment.TopStart)){EnergyValue("Solar",t.measure("pv_kw"),PilotAmber)}
 Column(Modifier.align(Alignment.TopEnd)){EnergyValue(if(t.optDouble("grid_kw")<0)"Grid export"else "Grid import",t.measure("grid_kw"),PilotCyan)}
 Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(12.dp)){EnergyValue("Home",t.measure("load_kw"),PilotCyan,Modifier.weight(1f));EnergyValue(if(t.optDouble("battery_kw")<0)"Battery charging"else "Battery supplying",t.measure("battery_kw"),PilotMint,Modifier.weight(1f))}
}}
@Composable fun EnergyChart(title:String,points:List<JSONObject>,series:List<Triple<String,String,Color>>){EnergyCard{Text(title,fontWeight=FontWeight.SemiBold);if(points.isEmpty())Text("History will appear when readings are available.",color=MaterialTheme.colorScheme.onSurfaceVariant)else{Canvas(Modifier.fillMaxWidth().height(200.dp)){val all=points.flatMap{p->series.mapNotNull{(k,_,_)->p.optDouble(k,Double.NaN).takeIf{it.isFinite()}}};val low=minOf(0.0,all.minOrNull()?:0.0);val high=maxOf(1.0,all.maxOrNull()?:1.0);series.forEach{(key,_,color)->val path=Path();var connected=false;points.forEachIndexed{i,p->val v=p.optDouble(key,Double.NaN);if(v.isFinite()){val x=i*size.width/(points.size-1).coerceAtLeast(1);val y=size.height-((v-low)/(high-low)*size.height).toFloat();if(connected)path.lineTo(x,y)else path.moveTo(x,y);connected=true}else connected=false};drawPath(path,color,style=Stroke(2.dp.toPx()))}}};Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(12.dp)){series.forEach{(_,name,color)->Text("● $name",fontSize=11.sp,color=color)}}}}
fun LazyListScope.housePlan(data:JSONObject){val p=data.obj("plan").obj("rolling");val n=p.obj("narrative");item{EnergyCard{Text(n.s("current_summary","Plan unavailable"),fontSize=20.sp,fontWeight=FontWeight.Bold);Text(n.s("headline","The manager replans as prices, weather and demand change."),color=MaterialTheme.colorScheme.onSurfaceVariant)}};item{EnergyChart("36-hour dispatch",p.arr("points").objects(),listOf(Triple("pv_kw","Solar",PilotAmber),Triple("load_kw","Home",PilotCyan)))};item{EnergyChart("Predicted battery",p.arr("points").objects(),listOf(Triple("predicted_soc_pct","Battery %",PilotMint)))};item{EnergyCard{Text("Next actions",fontWeight=FontWeight.SemiBold);n.arr("next_actions").objects().take(5).forEach{a->Row(horizontalArrangement=Arrangement.spacedBy(12.dp)){Text(a.s("at").drop(11).take(5),fontSize=12.sp,color=PilotMint);Text(a.s("title",a.s("summary",a.s("action"))))}}}}}
