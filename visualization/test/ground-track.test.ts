import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fetchGroundTrack} from '../src/ground-track.ts';
import {j2000Millis} from '../src/packet.ts';

const packetName = '/SHIRE_VISUAL/SHIRE_VISUAL_DATA';
const decode = (packet: {packet?: string}) =>
  packet.packet === undefined ? undefined : {utc: Number(packet.packet)};

for (const rate of [1, 20, 100]) {
  test(`${rate} Hz history includes the displayed point within the packet budget`, async () => {
    const center = 3600;
    const from = center - 1800;
    const requests: URLSearchParams[] = [];
    const recorded: number[] = [];
    // Simulate Yamcs's exclusive stop, inclusive start and continuation tokens
    // against a full hour of telemetry, rather than a pre-truncated fixture.
    const list = async (query: URLSearchParams) => {
      requests.push(new URLSearchParams(query));
      assert.equal(query.get('name'), packetName);
      assert.equal(query.get('order'), 'desc');
      const start = (Date.parse(query.get('start')!) - j2000Millis) / 1000;
      const stop = (Date.parse(query.get('stop')!) - j2000Millis) / 1000;
      const newestTick = Math.min(center * rate, Math.ceil(stop * rate) - 1);
      const oldestTick = Math.ceil(start * rate);
      const total = newestTick - oldestTick + 1;
      const offset = Number(query.get('next') || 0);
      const end = Math.min(total, offset + Number(query.get('limit')));
      const packets = Array.from({length: end - offset}, (_, i) =>
        ({packet: String((newestTick - offset - i) / rate)}));
      return {packets, continuationToken: end < total ? String(end) : undefined};
    };
    const coverage = await fetchGroundTrack({from, to: center, packetName, list,
      decode, record: sample => recorded.push(sample.utc), isCurrent: () => true});
    assert.equal(recorded[0], center);
    assert.ok(recorded.every(utc => utc >= from && utc <= center));
    assert.equal(recorded.length, Math.min(1800 * rate + 1, 12000));
    assert.deepEqual(coverage, [rate === 1 ? from : recorded.at(-1), center]);
    assert.equal(requests.length, Math.ceil(recorded.length / 400));
    for (const query of requests.slice(1)) {
      assert.equal(query.get('start'), requests[0].get('start'));
      assert.equal(query.get('stop'), requests[0].get('stop'));
      assert.ok(query.has('next'));
    }
  });
}

test('sparse and empty histories mark only the completed query as covered', async () => {
  for (const packets of [[], [{packet: '25'}, {}, {packet: '12'}]]) {
    const recorded: number[] = [];
    const coverage = await fetchGroundTrack({from: 0, to: 30, packetName,
      list: async () => ({packets}), decode,
      record: sample => recorded.push(sample.utc), isCurrent: () => true});
    assert.deepEqual(coverage, [0, 30]);
    assert.deepEqual(recorded, packets.length ? [25, 12] : []);
  }
});

test('a superseded seek discards its in-flight response', async () => {
  let current = true;
  const recorded: number[] = [];
  const coverage = await fetchGroundTrack({from: 0, to: 30, packetName,
    list: async () => {
      current = false;
      return {packets: [{packet: '30'}], continuationToken: 'older'};
    }, decode, record: sample => recorded.push(sample.utc),
    isCurrent: () => current});
  assert.equal(coverage, undefined);
  assert.deepEqual(recorded, []);
});

test('a failed archive request does not claim coverage', async () => {
  await assert.rejects(fetchGroundTrack({from: 0, to: 30, packetName,
    list: async () => {throw new Error('Yamcs archive 503');}, decode,
    record: () => assert.fail('No packets should be recorded'), isCurrent: () => true}),
  /Yamcs archive 503/);
});

test('truncated undecodable history does not claim coverage', async () => {
  let calls = 0;
  const coverage = await fetchGroundTrack({from: 0, to: 30, packetName,
    list: async () => {
      calls++;
      return {packets: Array.from({length: 400}, () => ({})), continuationToken: 'older'};
    }, decode, record: () => assert.fail('Invalid packets must be skipped'),
    isCurrent: () => true});
  assert.equal(calls, 30);
  assert.equal(coverage, undefined);
});
