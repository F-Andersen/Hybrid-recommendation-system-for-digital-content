"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiSend } from "@/lib/client-api";

export function LogoutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await apiSend("POST", "/auth/logout");
    } finally {
      router.push("/");
      router.refresh();
      setBusy(false);
    }
  }

  return (
    <button type="button" className="btn btn-small" onClick={logout} disabled={busy}>
      Вийти
    </button>
  );
}
