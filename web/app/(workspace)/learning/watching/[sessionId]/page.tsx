import WatchingSessionWorkspace from "@/components/watching/WatchingSessionWorkspace";

export default async function WatchingSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <WatchingSessionWorkspace sessionId={sessionId} />;
}
