"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { AdminUserRow, MeResponse } from "@/lib/api";
import { Spinner } from "@/components/ui";

async function jfetch(url: string, init: RequestInit = {}) {
  const res = await fetch(url, init);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(
      (data && (data.error ?? data.detail)) || `Lỗi HTTP ${res.status}`,
    );
  }
  return data;
}

export default function AdminUsersPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    email: "",
    password: "",
    display_name: "",
    workspace_name: "",
  });
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const meData = (await jfetch("/api/auth/me")) as MeResponse;
      setMe(meData);
      if (!meData.user?.is_system_admin) {
        setError("Tài khoản này không có quyền quản trị.");
        setUsers([]);
        return;
      }
      const list = (await jfetch("/api/admin/users")) as {
        users: AdminUserRow[];
      };
      setUsers(list.users ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tải thất bại.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await jfetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.email.trim(),
          password: form.password,
          display_name: form.display_name.trim() || undefined,
          workspace_name: form.workspace_name.trim() || undefined,
        }),
      });
      setForm({ email: "", password: "", display_name: "", workspace_name: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tạo user thất bại.");
    } finally {
      setCreating(false);
    }
  }

  async function toggleStatus(u: AdminUserRow) {
    const next = u.status === "active" ? "disabled" : "active";
    if (
      next === "disabled" &&
      !confirm(`Vô hiệu hóa ${u.email}? Họ sẽ bị đăng xuất ngay.`)
    )
      return;
    try {
      await jfetch(`/api/admin/users/${encodeURIComponent(u.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cập nhật thất bại.");
    }
  }

  async function resetPassword(u: AdminUserRow) {
    const pw = prompt(`Mật khẩu mới cho ${u.email} (tối thiểu 8 ký tự):`);
    if (!pw) return;
    try {
      await jfetch(
        `/api/admin/users/${encodeURIComponent(u.id)}/reset-password`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: pw }),
        },
      );
      alert(`Đã reset mật khẩu cho ${u.email}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reset thất bại.");
    }
  }

  async function deleteUser(u: AdminUserRow) {
    if (
      !confirm(
        `Xóa tài khoản ${u.email}? Workspace và dữ liệu của họ được GIỮ LẠI.`,
      )
    )
      return;
    try {
      await jfetch(`/api/admin/users/${encodeURIComponent(u.id)}`, {
        method: "DELETE",
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xóa thất bại.");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50dvh] items-center justify-center">
        <Spinner size={22} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-extrabold tracking-tight text-slate-900">
            Users
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {me?.user?.is_system_admin
              ? "Tạo tài khoản cho user. Mỗi user có workspace trống riêng."
              : "Khu vực quản trị."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/")}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 shadow-sm hover:bg-slate-50"
        >
          ← Dashboard
        </button>
      </div>

      {error ? (
        <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm font-semibold text-rose-700">
          {error}
        </p>
      ) : null}

      {me?.user?.is_system_admin ? (
        <>
          <form
            onSubmit={createUser}
            className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <h2 className="text-sm font-extrabold text-slate-900">
              Tạo user mới
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <input
                required
                type="email"
                placeholder="Email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <input
                required
                type="text"
                minLength={8}
                placeholder="Mật khẩu tạm (≥8 ký tự)"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <input
                type="text"
                placeholder="Tên hiển thị (tùy chọn)"
                value={form.display_name}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
                className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <input
                type="text"
                placeholder="Tên workspace (mặc định theo tên user)"
                value={form.workspace_name}
                onChange={(e) =>
                  setForm({ ...form, workspace_name: e.target.value })
                }
                className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
            </div>
            <button
              type="submit"
              disabled={creating}
              className="mt-4 inline-flex min-h-[42px] items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-500 disabled:opacity-60"
            >
              {creating ? <Spinner size={14} /> : null}
              {creating ? "Đang tạo…" : "Tạo user + workspace trống"}
            </button>
          </form>

          <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/60 text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">Workspace</th>
                  <th className="px-4 py-3">Trạng thái</th>
                  <th className="px-4 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-bold text-slate-900">
                        {u.display_name || u.email}
                        {u.is_system_admin ? (
                          <span className="ml-2 rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-black uppercase text-violet-700">
                            admin
                          </span>
                        ) : null}
                      </div>
                      <div className="text-xs text-slate-400">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {(u.workspaces ?? [])
                        .map((w) => `${w.workspace_name} (${w.role})`)
                        .join(", ") || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          u.status === "active"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-slate-200 text-slate-500"
                        }`}
                      >
                        {u.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => toggleStatus(u)}
                          className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50"
                        >
                          {u.status === "active" ? "Vô hiệu" : "Kích hoạt"}
                        </button>
                        <button
                          type="button"
                          onClick={() => resetPassword(u)}
                          className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50"
                        >
                          Reset MK
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteUser(u)}
                          className="rounded-lg border border-rose-200 px-2.5 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-50"
                        >
                          Xóa
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-8 text-center text-slate-400"
                    >
                      Chưa có user nào.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
