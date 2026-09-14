"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import { useToast } from "@/components/Toast";
import { Badge, Card, CardHeader, btnSmall } from "@/components/ui";
import {
  actionDisconnectDouyinSession,
  actionGetDouyinSessionAggregate,
  actionGetDouyinSessionFlow,
  actionStartDouyinSession,
  actionValidateDouyinSessionFull,
} from "@/lib/actions";

export function DouyinSessionPanel({ pipelineId }: { pipelineId: string }) {
  void pipelineId;
  const { toast } = useToast();
  const [, start] = useTransition();
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [flowId, setFlowId] = useState<string | null>(null);
  const [flowStatus, setFlowStatus] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPoll, [stopPoll]);

  const refreshAggregate = useCallback(() => {
    start(async () => {
      const r = await actionGetDouyinSessionAggregate();
      if (r.ok) {
        setConnected(!!r.connected);
        setAccount(r.accountName ?? null);
      }
    });
  }, []);

  useEffect(() => {
    refreshAggregate();
  }, [refreshAggregate]);

  const pollFlow = useCallback(
    (id: string) => {
      stopPoll();
      // Independent polling: no page refresh, only this component updates.
      pollRef.current = setInterval(() => {
        start(async () => {
          const r = await actionGetDouyinSessionFlow(id);
          if (!r.ok) {
            toast(r.error, "error");
            stopPoll();
            setPendingKey(null);
            return;
          }
          setFlowStatus(r.status ?? null);
          if (r.qrImageB64) setQr(r.qrImageB64);
          if (r.status === "connected") {
            stopPoll();
            setFlowId(null);
            setQr(null);
            setPendingKey(null);
            toast(`Douyin đã kết nối${r.accountName ? ` (${r.accountName})` : ""}.`, "success");
            refreshAggregate();
          } else if (r.status === "expired" || r.status === "failed") {
            stopPoll();
            setFlowId(null);
            setPendingKey(null);
            toast(r.errorDetail || "QR login hết hạn hoặc thất bại.", "error");
            refreshAggregate();
          }
        });
      }, 3000);
    },
    [refreshAggregate, stopPoll, toast],
  );

  const connect = () => {
    if (pendingKey) return;
    // Instant feedback: disable + spinner on first tap, no double-tap needed.
    setPendingKey("connect");
    setFlowStatus("starting");
    start(async () => {
      // Backend queues immediately (<500ms); QR arrives via background poll.
      const r = await actionStartDouyinSession();
      if (!r.ok || !r.sessionId) {
        setPendingKey(null);
        setFlowStatus(null);
        toast(r.ok ? "Không khởi tạo được QR login." : r.error, "error");
        return;
      }
      setFlowId(r.sessionId);
      setFlowStatus("pending");
      setQr(r.qrImageB64 ?? null);
      toast("Đã tạo QR login — đang mở trình duyệt nền.", "success");
      pollFlow(r.sessionId);
    });
  };

  const validate = () => {
    if (pendingKey) return;
    setPendingKey("validate");
    start(async () => {
      const r = await actionValidateDouyinSessionFull();
      setPendingKey(null);
      toast(r.ok ? "Douyin session hợp lệ." : r.error, r.ok ? "success" : "error");
      if (r.ok) refreshAggregate();
    });
  };

  const disconnect = () => {
    if (pendingKey) return;
    setPendingKey("disconnect");
    start(async () => {
      const r = await actionDisconnectDouyinSession();
      setPendingKey(null);
      toast(r.ok ? "Đã ngắt Douyin session." : r.error, r.ok ? "success" : "error");
      if (r.ok) {
        setConnected(false);
        setAccount(null);
      }
    });
  };

  return (
    <Card>
      <CardHeader
        title="Douyin Session"
        subtitle="QR login để retry khi anonymous scan bị challenge"
        action={
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btnSmall} disabled={pendingKey !== null} onClick={connect}>
              {pendingKey === "connect" ? "Đang mở QR…" : "Connect Douyin"}
            </button>
            <button type="button" className={btnSmall} disabled={pendingKey !== null} onClick={validate}>
              {pendingKey === "validate" ? "…" : "Validate"}
            </button>
            <button type="button" className={btnSmall} disabled={pendingKey !== null} onClick={disconnect}>
              {pendingKey === "disconnect" ? "…" : "Disconnect"}
            </button>
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-2 p-4 sm:px-5">
        {connected === null ? (
          <Badge tone="slate">Unknown</Badge>
        ) : connected ? (
          <Badge tone="green">Connected{account ? ` · ${account}` : ""}</Badge>
        ) : (
          <Badge tone="red">Login Required</Badge>
        )}
        {flowId ? (
          <Badge tone="amber">
            {qr ? "Waiting QR scan…" : "Đang mở trình duyệt lấy QR…"}
          </Badge>
        ) : null}
      </div>
      {flowId && !qr ? (
        <div className="border-t border-slate-100 p-4 sm:px-5">
          <div className="skeleton-bar h-48 w-full max-w-md rounded-xl" />
          <p className="mt-2 text-xs text-slate-500">Đang khởi tạo QR — không cần bấm lại, QR sẽ hiện sau vài giây.</p>
        </div>
      ) : null}
      {qr ? (
        <div className="border-t border-slate-100 p-4 sm:px-5">
          <p className="text-sm font-semibold text-slate-900">
            Quét QR bằng app Douyin {flowStatus ? `(${flowStatus})` : ""}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            Mở Douyin → góc trên →扫一扫. QR tự làm mới; trang tự cập nhật sau khi quét.
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/png;base64,${qr}`}
            alt="Douyin login QR"
            className="mt-3 w-full max-w-md rounded-xl border border-slate-200"
          />
        </div>
      ) : null}
    </Card>
  );
}
