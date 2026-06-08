import { getDigest } from "@/lib/api";

export default async function HomePage() {
  const digest = await getDigest();
  return (
    <main className="p-8">
      <h1 className="text-2xl font-bold mb-4">Event Tracker — Mock Mode</h1>
      <p className="text-sm text-gray-500 mb-4">Digest date: {digest.date} · {digest.picks.length} picks</p>
      <ul className="space-y-2">
        {digest.picks.map((p) => (
          <li key={p.event.id} className="border p-3 rounded">
            <strong>{p.event.title}</strong> — {p.event.venue_name}
            <p className="text-sm text-gray-600 mt-1">{p.justification}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
