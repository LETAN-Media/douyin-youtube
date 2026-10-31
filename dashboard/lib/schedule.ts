export interface ScheduleValues {
  daily_upload_limit?: number;
  upload_slots?: string[] | null;
  timezone?: string;
  publishing_start_time?: string;
  publishing_end_time?: string;
  publishing_overnight?: boolean;
  auto_distribute_upload_slots?: boolean;
  min_upload_interval_minutes?: number;
  backlog_slots_per_day?: number;
  new_slots_per_day?: number;
  slot_fallback_enabled?: boolean;
  schedule_override_enabled?: boolean;
  effective_schedule?: ScheduleValues & { source?: string; warnings?: string[] };
}

function minute(value: string): number {
  if (!/^\d{2}:\d{2}$/.test(value)) throw new Error("Giờ phải có định dạng HH:MM.");
  const [h,m]=value.split(":").map(Number);
  if(h>23||m>59) throw new Error("Giờ không hợp lệ.");
  return h*60+m;
}

export function generateSlots(count:number,start:string,end:string,overnight=false,minimum=1):string[] {
  if(!Number.isInteger(count)||count<1) throw new Error("Daily Upload Limit phải là số nguyên dương.");
  const a=minute(start); let b=minute(end);
  if(b<a) { if(!overnight) throw new Error("Hãy bật lịch qua nửa đêm khi giờ kết thúc trước giờ bắt đầu."); b+=1440; }
  else if(overnight) throw new Error("Lịch qua nửa đêm cần giờ kết thúc trước giờ bắt đầu.");
  if(count>1&&Math.floor((b-a)/(count-1))<minimum) throw new Error(`Không đủ chỗ cho ${count} slot cách nhau ít nhất ${minimum} phút.`);
  const values=Array.from({length:count},(_,i)=>count===1?a:a+Math.floor((i*(b-a)+Math.floor((count-1)/2))/(count-1)));
  if(new Set(values.map(v=>v%1440)).size!==count) throw new Error("Lịch tạo ra giờ trùng nhau.");
  return values.map(v=>`${String(Math.floor((v%1440)/60)).padStart(2,"0")}:${String(v%60).padStart(2,"0")}`);
}

export function validateManualSlots(slots:string[],count:number,start:string,end:string,overnight=false,minimum=1):void {
  if(slots.length!==count) throw new Error(`Cần ${count} slot thủ công; hiện có ${slots.length}.`);
  if(new Set(slots).size!==slots.length) throw new Error("Có giờ đăng trùng nhau.");
  const a=minute(start),b=minute(end)+(overnight?1440:0);
  const times=slots.map(s=>minute(s)+(overnight&&minute(s)<a?1440:0)).sort((x,y)=>x-y);
  if(times.some(t=>t<a||t>b)) throw new Error("Giờ đăng nằm ngoài khoảng đã chọn.");
  if(times.some((t,i)=>i>0&&t-times[i-1]<minimum)||(times.length>1&&1440-times.at(-1)!+times[0]<minimum)) throw new Error(`Các slot phải cách nhau ít nhất ${minimum} phút, kể cả giữa hai ngày.`);
}

export function scheduleFormData(form:FormData,destination=false):Record<string,unknown> {
  const override=form.get("schedule_override_enabled")==="true";
  if(destination&&!override) return {schedule_override_enabled:false};
  return {
    ...(destination?{schedule_override_enabled:true}:{}),
    daily_upload_limit:Number(form.get("daily_upload_limit")),
    upload_slots:String(form.get("upload_slots")??"").split(/[\s,]+/).filter(Boolean),
    timezone:String(form.get("timezone")??"UTC"),
    publishing_start_time:String(form.get("publishing_start_time")??"08:00"),
    publishing_end_time:String(form.get("publishing_end_time")??"23:00"),
    auto_distribute_upload_slots:form.get("auto_distribute_upload_slots")==="on",
    publishing_overnight:form.get("publishing_overnight")==="on",
    min_upload_interval_minutes:Number(form.get("min_upload_interval_minutes")??1),
    backlog_slots_per_day:Number(form.get("backlog_slots_per_day")??0),
    new_slots_per_day:Number(form.get("new_slots_per_day")??0),
    slot_fallback_enabled:form.get("slot_fallback_enabled")==="on",
  };
}
