import { AppShell } from "@/components/app-shell";
import { SocketProvider } from "@/lib/realtime/socket-provider";

export default function AuthedLayout({ children }: { children: React.ReactNode }) {
  return (
    <SocketProvider>
      <AppShell>{children}</AppShell>
    </SocketProvider>
  );
}
