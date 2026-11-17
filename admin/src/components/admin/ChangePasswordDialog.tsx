import { useId, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { AdminField } from "./AdminField";
import { AdminModal } from "./AdminModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ChangePasswordDialog({ email, resetUserId, onClose }: { email?: string; resetUserId?: number; onClose: () => void }) {
  const resetting = resetUserId !== undefined;
  const formId = useId();
  const pending = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const form = new FormData(event.currentTarget);
    const current = form.get("current");
    const password = String(form.get("password"));
    if (password !== form.get("confirm")) return setError("两次输入的新密码不一致");
    if (!resetting && current === password) return setError("新密码不能与当前密码相同");
    if (new TextEncoder().encode(password).length > 72) return setError("新密码过长，请缩短后重试");
    pending.current = true;
    setSaving(true);
    setError("");
    try {
      await api(resetting ? `/api/admin/users/${resetUserId}/reset-password` : "/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify(resetting ? { new_password: password } : { current_password: current, new_password: password }),
      });
      toast.success(resetting ? `已重置 ${email} 的登录密码` : "登录密码已修改");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改密码失败，请重试");
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return (
    <AdminModal open onOpenChange={open => { if (!open && !pending.current) onClose(); }}
      title={resetting ? "重置用户密码" : "修改登录密码"} subtitle={email} size="md"
      footer={<>
        <Button type="button" variant="outline" disabled={saving} onClick={onClose}>取消</Button>
        <Button type="submit" form={formId} disabled={saving}>{saving ? "正在保存…" : resetting ? "确认重置" : "保存密码"}</Button>
      </>}>
      <form id={formId} className="space-y-4" onSubmit={submit} onChange={() => setError("")}>
        <input type="hidden" name="username" autoComplete="username" value={email ?? ""} />
        {!resetting && <AdminField label="当前密码" required>
          <Input type="password" name="current" autoComplete="current-password" maxLength={64} disabled={saving} />
        </AdminField>}
        <AdminField label="新密码" required hint="请输入 6 至 64 个字符。">
          <Input type="password" name="password" autoComplete="new-password" minLength={6} maxLength={64} disabled={saving} />
        </AdminField>
        <AdminField label="确认新密码" required>
          <Input type="password" name="confirm" autoComplete="new-password" maxLength={64} disabled={saving} />
        </AdminField>
        {error && <p role="alert" className="admin-field-error">{error}</p>}
      </form>
    </AdminModal>
  );
}
