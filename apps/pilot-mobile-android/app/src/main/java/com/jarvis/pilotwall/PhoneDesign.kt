package com.jarvis.pilotwall
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.geometry.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*

@Composable fun PhoneTabs(selected:String,onSelect:(String)->Unit){Surface(color=MaterialTheme.colorScheme.surface){Column{HorizontalDivider(thickness=.5.dp);Row(Modifier.fillMaxWidth().height(60.dp)){listOf("Home","Control","Energy","Pilot","More").forEach{title->val active=title==selected;val color=if(active)MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant;Column(Modifier.weight(1f).fillMaxHeight().clickable{onSelect(title)}.semantics{contentDescription=title;this.selected=active},horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.Center){PilotIcon(title,color=color);Spacer(Modifier.height(4.dp));Text(title,fontSize=10.sp,color=color)}}}}}}
@Composable fun PhoneSegments(items:List<String>,selected:String,onSelect:(String)->Unit){Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.onSurface.copy(alpha=.08f),RoundedCornerShape(8.dp)).padding(3.dp)){items.forEach{title->Box(Modifier.weight(1f).background(if(title==selected)MaterialTheme.colorScheme.surface else Color.Transparent,RoundedCornerShape(6.dp)).clickable{onSelect(title)}.padding(vertical=8.dp),contentAlignment=Alignment.Center){Text(title,fontSize=12.sp,fontWeight=if(title==selected)FontWeight.SemiBold else FontWeight.Normal,maxLines=1)}}}}
@Composable fun PilotIcon(name:String,modifier:Modifier=Modifier.size(22.dp),color:Color=MaterialTheme.colorScheme.primary){
 Canvas(modifier){val u=size.minDimension/24;val sw=1.8f*u;fun line(x:Float,y:Float,a:Float,b:Float)=drawLine(color,Offset(x*u,y*u),Offset(a*u,b*u),sw,StrokeCap.Round)
 when(name){
 "Home"->{val p=Path().apply{moveTo(2*u,11*u);lineTo(12*u,2*u);lineTo(22*u,11*u)};drawPath(p,color,style=Stroke(sw));line(5f,10f,5f,22f);line(5f,22f,19f,22f);line(19f,22f,19f,10f);line(10f,22f,10f,15f);line(10f,15f,14f,15f);line(14f,15f,14f,22f)}
 "Control"->{drawRoundRect(color,Offset(2*u,3*u),Size(20*u,15*u),CornerRadius(4*u),style=Stroke(sw));line(6f,18f,6f,22f);line(6f,22f,11f,18f);line(6f,8f,18f,8f);line(6f,12f,14f,12f)}
 "Energy"->{val p=Path().apply{moveTo(14*u,1*u);lineTo(4*u,14*u);lineTo(11*u,14*u);lineTo(9*u,23*u);lineTo(21*u,9*u);lineTo(13*u,9*u);close()};drawPath(p,color,style=Stroke(sw))}
 "Pilot"->{for((x,h) in listOf(3f to 3f,7f to 6f,11f to 10f,15f to 7f,19f to 4f,23f to 2f))line(x,12-h,x,12+h)}

 "Overview","gauge"->{drawArc(color,150f,240f,false,Offset(3*u,3*u),Size(18*u,18*u),style=Stroke(sw,cap=StrokeCap.Round));line(12f,12f,17f,7f);drawCircle(color,2*u,Offset(12*u,12*u))}
 "Budget","pie"->{drawArc(color,0f,270f,true,Offset(3*u,3*u),Size(18*u,18*u));drawArc(color.copy(alpha=.45f),275f,80f,true,Offset(5*u,u),Size(18*u,18*u))}
 "Payday","calendar"->{drawRoundRect(color,Offset(3*u,5*u),Size(18*u,16*u),CornerRadius(2*u),style=Stroke(sw));line(7f,3f,7f,7f);line(17f,3f,17f,7f);line(3f,10f,21f,10f);line(8f,15f,11f,18f);line(11f,18f,16f,13f)}
 "Transactions","list"->{drawRoundRect(color,Offset(2*u,4*u),Size(20*u,16*u),CornerRadius(2*u),style=Stroke(sw));for(y in listOf(8f,12f,16f)){line(6f,y,7f,y);line(11f,y,18f,y)}}
 "bank"->{val p=Path().apply{moveTo(2*u,8*u);lineTo(12*u,2*u);lineTo(22*u,8*u);close()};drawPath(p,color);for(x in listOf(5f,12f,19f))line(x,11f,x,19f);line(2f,22f,22f,22f)}
 "card"->{drawRoundRect(color,Offset(2*u,5*u),Size(20*u,14*u),CornerRadius(2*u),style=Stroke(sw));line(2f,10f,22f,10f);line(5f,15f,10f,15f)}
 "sync"->{drawArc(color,35f,280f,false,Offset(4*u,4*u),Size(16*u,16*u),style=Stroke(sw,cap=StrokeCap.Round));line(20f,3f,20f,9f);line(15f,8f,20f,9f)}
 "gift"->{drawRect(color,Offset(3*u,10*u),Size(18*u,11*u),style=Stroke(sw));line(12f,7f,12f,21f);line(2f,8f,22f,8f);drawOval(color,Offset(6*u,2*u),Size(6*u,6*u),style=Stroke(sw));drawOval(color,Offset(12*u,2*u),Size(6*u,6*u),style=Stroke(sw))}
 "health"->{line(2f,12f,6f,12f);line(6f,12f,9f,5f);line(9f,5f,13f,20f);line(13f,20f,17f,9f);line(17f,9f,20f,12f);line(20f,12f,23f,12f)}
 "chevron"->{line(9f,6f,15f,12f);line(15f,12f,9f,18f)}
 "plus"->{line(12f,4f,12f,20f);line(4f,12f,20f,12f)}
 "check"->{drawCircle(color,9*u,Offset(12*u,12*u),style=Stroke(sw));line(7f,12f,10f,15f);line(10f,15f,17f,8f)}
 "warning"->{val p=Path().apply{moveTo(12*u,2*u);lineTo(23*u,21*u);lineTo(u,21*u);close()};drawPath(p,color,style=Stroke(sw));line(12f,8f,12f,13f);drawCircle(color,u,Offset(12*u,17*u))}
 "More"->{for(x in listOf(5f,12f,19f))drawCircle(color,1.8f*u,Offset(x*u,12*u))}
 else->{drawCircle(color,8*u,Offset(12*u,12*u),style=Stroke(sw));drawCircle(color,3*u,Offset(12*u,12*u),style=Stroke(sw))}
 }}
}
