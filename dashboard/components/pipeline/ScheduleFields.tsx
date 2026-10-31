"use client";
import { useEffect, useId, useState } from "react";
import { generateSlots, validateManualSlots } from "@/lib/schedule";
import type { ScheduleValues } from "@/lib/schedule";
import { inputCls, labelCls } from "@/components/ui";

export function ScheduleFields({initial,destination=false}:{initial:ScheduleValues;destination?:boolean}) {
  const saved=initial.effective_schedule??initial;
  const id=useId();
  const [override,setOverride]=useState(initial.schedule_override_enabled??false);
  const [count,setCount]=useState(saved.daily_upload_limit??4);
  const [start,setStart]=useState(saved.publishing_start_time??"08:00");
  const [end,setEnd]=useState(saved.publishing_end_time??"23:00");
  const [auto,setAuto]=useState(saved.auto_distribute_upload_slots??true);
  const [overnight,setOvernight]=useState(saved.publishing_overnight??false);
  const [minimum,setMinimum]=useState(Math.max(1,saved.min_upload_interval_minutes??1));
  const [manual,setManual]=useState(saved.upload_slots??[]);
  const initialTotal=(saved.backlog_slots_per_day??0)+(saved.new_slots_per_day??0);
  const [backlog,setBacklog]=useState(initialTotal?Math.round(count*(saved.backlog_slots_per_day??0)/initialTotal):0);
  const [policy,setPolicy]=useState<{max_daily_uploads?:number;minimum_interval_minutes:number;warning_threshold:number}>({minimum_interval_minutes:1,warning_threshold:20});
  useEffect(()=>{
    const abort=new AbortController();
    fetch("/api/scheduler/policy",{signal:abort.signal}).then(r=>r.ok?r.json():null).then(p=>{if(p)setPolicy(p);}).catch(()=>{});
    return ()=>abort.abort();
  },[]);
  const enabled=!destination||override;
  let generated:string[]=[],error="";
  try {
    if(policy.max_daily_uploads&&count>policy.max_daily_uploads) throw new Error(`Vượt giới hạn an toàn đã cấu hình: ${policy.max_daily_uploads}.`);
    generated=generateSlots(count,start,end,overnight,Math.max(minimum,policy.minimum_interval_minutes));
  } catch(e) {error=e instanceof Error?e.message:"Lịch không hợp lệ.";}
  const slots=auto?generated:manual;
  if(!error) {
    try {validateManualSlots(slots,count,start,end,overnight,Math.max(minimum,policy.minimum_interval_minutes));}
    catch(e) {error=e instanceof Error?e.message:"Lịch thủ công không hợp lệ.";}
  }
  const changeCount=(next:number)=>{setBacklog(count>0?Math.round(next*backlog/count):0);setCount(next);};
  return <section className="space-y-3 sm:col-span-2" aria-label="Upload schedule">
    <div className="rounded-xl bg-slate-50 p-3 text-sm">
      <p><strong>Effective Daily Limit:</strong> {saved.daily_upload_limit??4} · {initial.effective_schedule?.source??(destination?"destination":"pipeline")}</p>
      <p><strong>Effective Upload Slots:</strong> {(saved.upload_slots??[]).join(", ")} ({saved.timezone??"UTC"})</p>
      {initial.effective_schedule?.warnings?.map(w=><p key={w} className="text-amber-700">{w}</p>)}
    </div>
    {destination&&<><input type="hidden" name="schedule_override_enabled" value={String(override)}/><label className="flex gap-2 text-sm"><input type="checkbox" checked={override} onChange={e=>setOverride(e.target.checked)}/>Override lịch riêng cho Destination này</label><p className="text-xs text-slate-500">Tắt override để dùng mặc định từ Pipeline. Lịch riêng cũ được giữ nguyên cho đến khi bạn chủ động tắt override.</p></>}
    <fieldset disabled={!enabled} className="grid gap-3 sm:grid-cols-2 disabled:opacity-60">
      <label className={labelCls} htmlFor={`${id}-limit`}>Daily Upload Limit<input id={`${id}-limit`} name="daily_upload_limit" type="number" required min={1} step={1} max={policy.max_daily_uploads} value={Number.isFinite(count)?count:""} onChange={e=>changeCount(Number(e.target.value))} className={inputCls}/></label>
      <label className={labelCls}>Timezone<input name="timezone" defaultValue={saved.timezone??"UTC"} required className={inputCls}/></label>
      <label className={labelCls}>Publishing Start Time<input name="publishing_start_time" type="time" required value={start} onChange={e=>setStart(e.target.value)} className={inputCls}/></label>
      <label className={labelCls}>Publishing End Time<input name="publishing_end_time" type="time" required value={end} onChange={e=>setEnd(e.target.value)} className={inputCls}/></label>
      <label className="flex gap-2 text-sm"><input name="auto_distribute_upload_slots" type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/>Auto Distribute Upload Slots</label>
      <label className="flex gap-2 text-sm"><input name="publishing_overnight" type="checkbox" checked={overnight} onChange={e=>setOvernight(e.target.checked)}/>Cho phép qua nửa đêm</label>
      <label className={labelCls}>Khoảng cách tối thiểu (phút)<input name="min_upload_interval_minutes" type="number" required min={policy.minimum_interval_minutes} step={1} value={minimum} onChange={e=>setMinimum(Number(e.target.value))} className={inputCls}/></label>
      <label className={labelCls}>Backlog slots/day<input name="backlog_slots_per_day" type="number" min={0} max={count} step={1} value={backlog} onChange={e=>setBacklog(Number(e.target.value))} className={inputCls}/></label>
      <label className={labelCls}>New slots/day<input name="new_slots_per_day" type="number" readOnly value={Math.max(0,count-backlog)} className={inputCls}/></label>
      <label className="flex gap-2 text-sm"><input name="slot_fallback_enabled" type="checkbox" defaultChecked={saved.slot_fallback_enabled??true}/>Dùng nhóm còn lại khi hết video</label>
      <div className="sm:col-span-2"><button type="button" disabled={!!error&&auto} onClick={()=>{if(generated.length)setManual(generated);}} className="rounded-lg border px-3 py-2 text-sm">Generate Slots</button></div>
      <input type="hidden" name="upload_slots" value={slots.join(",")}/>
      <div className="sm:col-span-2"><p className="text-sm font-semibold">Upload Slots Preview — {slots.length}/{count} (chưa lưu)</p><ol className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">{slots.map((time,i)=><li key={i} className="rounded border p-2 text-xs"><span>{i+1}. </span>{auto?time:<input aria-label={`Slot ${i+1}`} type="time" required value={time} onChange={e=>setManual(old=>old.map((t,j)=>j===i?e.target.value:t))} className="w-full"/>}{!auto&&<button type="button" aria-label={`Xóa slot ${i+1}`} onClick={()=>setManual(old=>old.filter((_,j)=>j!==i))}>×</button>}</li>)}</ol>{!auto&&<button type="button" className="mt-2 text-sm" onClick={()=>setManual(old=>[...old,start])}>+ Thêm slot</button>}</div>
    </fieldset>
    {enabled&&error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
    {count>=policy.warning_threshold&&<p className="text-sm text-amber-700">Số video/ngày cao. Hãy kiểm tra quota YouTube và lượng video nguồn; hệ thống sẽ tạm dừng nếu quota không đủ.</p>}
    <p className="text-xs text-slate-500">Preview không ghi database. Chỉ Save mới lưu đồng bộ limit và slots. Job/Publication đã Scheduled giữ nguyên; lịch mới chỉ áp dụng cho slot tương lai.</p>
  </section>;
}
