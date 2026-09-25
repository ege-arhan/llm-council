import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function mockStream(parts) {
  const encoder = new TextEncoder();
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  }), { status: 200 });
}

test('SSE frames split across network chunks are delivered once', async () => {
  mockStream(['data: {"type":"stage1_', 'complete","data":[1]}\n\ndata: {"type":"complete"}\n', '\n']);
  const events = [];
  await api.sendMessageStream('conversation-id', 'question', (type, data) => events.push([type, data]));
  assert.deepEqual(events.map(([type]) => type), ['stage1_complete', 'complete']);
  assert.deepEqual(events[0][1].data, [1]);
});

test('a dropped stream cannot be mistaken for a completed council', async () => {
  mockStream(['data: {"type":"stage1_complete"}\n\n']);
  await assert.rejects(api.sendMessageStream('conversation-id', 'question', () => {}), /before completion/);
});
