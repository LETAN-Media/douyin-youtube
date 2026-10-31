import test from "node:test";
import assert from "node:assert/strict";
import {generateSlots,validateManualSlots,scheduleFormData} from "../lib/schedule.ts";
for(const n of [1,3,5,6,10,15,20]) test(`${n} evenly distributed slots`,()=>{
  const slots=generateSlots(n,"08:00","23:00");assert.equal(slots.length,n);assert.equal(new Set(slots).size,n);assert.equal(slots[0],"08:00");if(n>1)assert.equal(slots.at(-1),"23:00");
});
test("exact ten-slot example",()=>assert.deepEqual(generateSlots(10,"08:00","23:00"),["08:00","09:40","11:20","13:00","14:40","16:20","18:00","19:40","21:20","23:00"]));
test("overnight requires explicit choice",()=>{assert.throws(()=>generateSlots(5,"22:00","02:00"));assert.deepEqual(generateSlots(5,"22:00","02:00",true),["22:00","23:00","00:00","01:00","02:00"]);});
test("manual duplicates, spacing and range are rejected",()=>{assert.throws(()=>validateManualSlots(["08:00","08:00"],2,"08:00","23:00"));assert.throws(()=>validateManualSlots(["08:00","08:01"],2,"08:00","23:00",false,5));assert.throws(()=>validateManualSlots(["07:00"],1,"08:00","23:00"));});
test("inherit does not submit stale destination drafts",()=>{const form=new FormData();form.set("schedule_override_enabled","false");form.set("daily_upload_limit","4");assert.deepEqual(scheduleFormData(form,true),{schedule_override_enabled:false});});
test("invalid limits or impossible windows do not clamp",()=>{for(const n of [0,-1,1.5])assert.throws(()=>generateSlots(n,"08:00","23:00"));assert.throws(()=>generateSlots(10,"08:00","08:05"));});
