"use client";

import { useEffect, useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";

export function PipelineFlow({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    let mounted = true;
    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/flow-status`);
        if (!res.ok) throw new Error("Failed");
        const json = await res.json();
        if (mounted) {
          setData(json);
          setError(false);
        }
      } catch (err) {
        if (mounted) setError(true);
      }
    };

    void fetchStatus();
    // 5 seconds polling
    const intervalId = setInterval(() => {
      if (document.visibilityState === "visible") {
        void fetchStatus();
      }
    }, 5000);
    
    // Check if visibility changes to fetch immediately
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void fetchStatus();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      mounted = false;
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [pipeline.id]);

  if (error) return <div className="text-sm text-rose-500">Lỗi tải trạng thái luồng hoạt động.</div>;
  if (!data) return <div className="animate-pulse h-32 rounded-2xl bg-slate-100"></div>;

  const {
    worker_alive,
    current_job,
    steps = [],
    queue_preview = [],
    recent_failures = [],
    latest_success,
    counts,
  } = data;

  return (
    <div className="space-y-4">
      {/* FLOW BLOCK */}
      <div className="rounded-2xl bg-white p-4 shadow-sm border border-slate-100 relative overflow-hidden">
        {/* Header Badges */}
        <div className="flex flex-wrap items-center justify-between mb-4 gap-2">
          <h2 className="text-sm font-extrabold text-slate-800 uppercase tracking-wider">
            Flow Hoạt Động
          </h2>
          <div className="flex items-center gap-2">
            {!pipeline.auto_publish && pipeline.pipeline_type !== "manual" && (
              <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[10px] font-bold text-amber-800 whitespace-nowrap">
                Tự động đăng tắt
              </span>
            )}
            {!worker_alive && (
              <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-[10px] font-bold text-rose-700 whitespace-nowrap">
                Worker Offline
              </span>
            )}
          </div>
        </div>

        {/* Steps */}
        <div className="flex w-full items-start justify-start overflow-x-auto pb-4 pt-2 -mx-2 px-2 scrollbar-hide">
          <div className="flex min-w-max items-center">
            {steps.map((step: any, index: number) => {
              const isLast = index === steps.length - 1;
              const isRunning = step.state === "running";
              const isDone = step.state === "done";
              const isWarning = step.state === "warning";
              const isFailed = step.state === "failed";
              
              let circleColor = "border-slate-200 bg-white text-slate-400";
              let labelColor = "text-slate-500";
              let dot = null;
              
              if (isRunning) {
                circleColor = "border-indigo-500 bg-indigo-50 text-indigo-700 ring-4 ring-indigo-50";
                labelColor = "text-indigo-700 font-extrabold";
                dot = <span className="absolute inline-flex h-2 w-2 rounded-full bg-indigo-500 animate-ping opacity-75"></span>;
              } else if (isDone) {
                circleColor = "border-emerald-500 bg-emerald-50 text-emerald-700";
                labelColor = "text-emerald-700 font-bold";
              } else if (isFailed) {
                circleColor = "border-rose-500 bg-rose-50 text-rose-700";
                labelColor = "text-rose-700 font-bold";
              } else if (isWarning) {
                circleColor = "border-amber-500 bg-amber-50 text-amber-700";
                labelColor = "text-amber-700 font-bold";
              }

              return (
                <div key={step.key} className="flex items-center">
                  <div className="flex flex-col items-center gap-2 group relative">
                    <div className={`relative flex h-8 w-8 items-center justify-center rounded-full border-2 transition-all duration-300 ${circleColor}`}>
                      {dot}
                      {isDone && (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>
                      )}
                      {!isDone && (
                        <span className="text-xs font-bold">{index + 1}</span>
                      )}
                    </div>
                    <span className={`text-[10px] text-center w-20 leading-tight transition-colors duration-300 ${labelColor}`}>
                      {step.label}
                    </span>
                  </div>
                  {!isLast && (
                    <div className="relative mx-1 mb-6 flex h-0.5 w-10 sm:w-16 flex-col justify-center rounded-full bg-slate-100">
                      {isRunning && (
                        <div className="absolute left-0 top-0 h-full w-1/3 rounded-full bg-indigo-400 animate-[runningLine_1.5s_ease-in-out_infinite]"></div>
                      )}
                      {isDone && (
                        <div className="absolute left-0 top-0 h-full w-full rounded-full bg-emerald-300 transition-all duration-500"></div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Current Job vs Queue Panel */}
        <div className="mt-2 grid grid-cols-1 lg:grid-cols-2 gap-4">
          
          {/* Left Column: Current Job & Success/Failures */}
          <div className="space-y-4">
            {/* Current Job */}
            {current_job ? (
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-3 relative overflow-hidden group">
                <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500 rounded-l-xl"></div>
                {current_job.stage && current_job.stage.includes("running") && (
                   <div className="absolute top-0 left-0 w-full h-1 bg-indigo-100">
                      <div className="h-full bg-indigo-500 transition-all duration-500 ease-in-out" style={{ width: `${current_job.progress_percent}%` }}></div>
                   </div>
                )}
                <div className="flex justify-between items-start mb-1">
                  <span className="text-[10px] font-extrabold uppercase text-indigo-600 tracking-wider flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse"></span>
                    Đang xử lý
                  </span>
                  <span className="text-[10px] font-bold text-slate-500">
                    {current_job.progress_percent}%
                  </span>
                </div>
                <div className="font-medium text-sm text-slate-900 truncate">
                  {current_job.caption}
                </div>
                <div className="flex justify-between items-end mt-2">
                  <div className="text-xs text-slate-500 font-mono bg-white px-2 py-0.5 rounded-md border border-slate-200">
                    ID: {current_job.video_id.substring(0, 15)}...
                  </div>
                  <div className="text-[10px] text-slate-400">
                    Cập nhật: {new Date(current_job.updated_at).toLocaleTimeString('vi-VN')}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4 flex flex-col items-center justify-center text-center h-24">
                <span className="text-slate-400 text-xs font-bold mb-1">Hiện không có job đang chạy</span>
                <span className="text-[10px] text-slate-400">Hệ thống đang rảnh hoặc đang chờ video mới</span>
              </div>
            )}

            {/* Success & Failures Row */}
            <div className="grid grid-cols-2 gap-3">
              {latest_success ? (
                <div className="rounded-xl border border-emerald-100 bg-emerald-50/30 p-2.5">
                  <div className="text-[10px] font-bold uppercase text-emerald-600 mb-1">Đăng gần nhất</div>
                  <a href={latest_success.youtube_url} target="_blank" rel="noreferrer" className="text-xs font-semibold text-emerald-700 hover:underline truncate block">
                    {latest_success.youtube_url}
                  </a>
                </div>
              ) : (
                <div className="rounded-xl border border-slate-100 bg-slate-50 p-2.5">
                  <div className="text-[10px] font-bold uppercase text-slate-500 mb-1">Đăng gần nhất</div>
                  <div className="text-xs text-slate-400">Chưa có video nào</div>
                </div>
              )}

              {recent_failures.length > 0 ? (
                <div className="rounded-xl border border-rose-100 bg-rose-50/30 p-2.5">
                  <div className="text-[10px] font-bold uppercase text-rose-600 mb-1 flex items-center justify-between">
                    <span>Lỗi gần đây</span>
                    <span className="bg-rose-200 text-rose-800 rounded-full w-4 h-4 flex items-center justify-center text-[9px]">{counts?.failed || 0}</span>
                  </div>
                  <div className="text-[11px] font-semibold text-rose-700 truncate" title={recent_failures[0].error_code}>
                    {recent_failures[0].video_id}
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-slate-100 bg-slate-50 p-2.5">
                  <div className="text-[10px] font-bold uppercase text-slate-500 mb-1">Lỗi gần đây</div>
                  <div className="text-xs text-slate-400">Không có lỗi</div>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Queue */}
          <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 max-h-48 overflow-y-auto scrollbar-thin">
            <div className="flex justify-between items-center mb-2 sticky top-0 bg-slate-50 py-1">
              <span className="text-xs font-bold text-slate-700">Hàng chờ tiếp theo</span>
              <span className="text-[10px] font-bold bg-slate-200 text-slate-600 px-2 py-0.5 rounded-full">
                Còn {counts?.available || 0}
              </span>
            </div>
            
            {queue_preview.length === 0 ? (
              <div className="py-6 flex flex-col items-center justify-center text-center">
                <svg className="w-8 h-8 text-slate-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" /></svg>
                <p className="text-xs text-slate-400 font-medium">Không có video chờ đăng</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {queue_preview.map((item: any, idx: number) => (
                  <div key={item.inventory_id} className="flex items-center gap-2 bg-white p-2 rounded-lg border border-slate-100 hover:border-slate-200 transition-colors">
                    <span className="w-5 text-center text-[10px] font-bold text-slate-400">#{idx + 1}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-slate-800 truncate" title={item.caption}>
                        {item.caption || "Không có tiêu đề"}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] text-slate-500 font-mono truncate">{item.video_id}</span>
                        <span className="text-[9px] px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded">
                          {item.source_label}
                        </span>
                      </div>
                    </div>
                    <div>
                      {item.status === 'processing' ? (
                        <span className="w-2 h-2 rounded-full bg-indigo-500 block animate-pulse"></span>
                      ) : (
                        <span className="w-2 h-2 rounded-full bg-amber-400 block"></span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </div>
      
      {/* Required custom CSS for the line animation */}
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes runningLine {
          0% { transform: translateX(-100%); opacity: 0; }
          50% { opacity: 1; }
          100% { transform: translateX(300%); opacity: 0; }
        }
      `}} />
    </div>
  );
}
