import {j2000Millis} from './packet.ts';

type Packet = {packet?: string};
type Page = {packets?: Packet[]; continuationToken?: string};
type TrackRequest<T extends {utc: number}> = {
  from: number;
  to: number;
  packetName: string;
  list: (query: URLSearchParams) => Promise<Page>;
  decode: (packet: Packet) => T | undefined;
  record: (sample: T) => void;
  isCurrent: () => boolean;
};

/** Load bounded recorded history, always starting at the displayed time. */
export async function fetchGroundTrack<T extends {utc: number}>(
  request: TrackRequest<T>
): Promise<[number, number] | undefined> {
  const {from, to, packetName, list, decode, record, isCurrent} = request;
  const query = new URLSearchParams({name: packetName, order: 'desc', limit: '400',
    start: new Date(j2000Millis + from * 1000).toISOString(),
    // Yamcs stop is exclusive. Include the packet at the displayed millisecond.
    stop: new Date(Math.floor(j2000Millis + to * 1000) + 1).toISOString()});
  let oldest: number | undefined;
  for (let count = 0; count < 12000;) {
    const page = await list(query);
    if (!isCurrent()) return undefined;
    for (const packet of page.packets || []) {
      const sample = decode(packet);
      if (sample) {
        record(sample);
        oldest = Math.min(oldest ?? sample.utc, sample.utc);
      }
    }
    count += (page.packets || []).length;
    // Exhausting the query covers gaps as well as successfully decoded packets.
    if (!page.continuationToken) return [from, to];
    if (count >= 12000) break;
    query.set('next', page.continuationToken);
  }
  // Never claim the unfetched portion of a truncated history window.
  return oldest === undefined ? undefined : [oldest, to];
}
