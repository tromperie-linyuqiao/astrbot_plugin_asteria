/* Browser-only helpers for the existing HTTP AstrBot plugin-page host.
 * Request IDs always use browser cryptographic randomness. SHA-256 is local,
 * deterministic and operates on a copied byte snapshot; no network or storage.
 */
(function (root, factory) {
  'use strict';
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TLSBrowserCompat = api;
})(typeof globalThis === 'object' ? globalThis : this, function (root) {
  'use strict';
  const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

  function uuid() {
    let provider;
    try { provider = root.crypto; } catch (_) { /* fail closed below */ }
    if (provider && typeof provider.randomUUID === 'function') {
      try {
        const value = provider.randomUUID();
        if (typeof value === 'string' && UUID_V4.test(value)) return value;
      } catch (_) { /* getRandomValues remains available on HTTP origins */ }
    }
    if (!provider || typeof provider.getRandomValues !== 'function')
      throw Error('A secure browser random source is required for request IDs.');
    const bytes = new Uint8Array(16);
    provider.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const text = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    return text.slice(0, 8) + '-' + text.slice(8, 12) + '-' + text.slice(12, 16)
      + '-' + text.slice(16, 20) + '-' + text.slice(20);
  }

  function byteSnapshot(value) {
    let view;
    const byteLength = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'byteLength').get;
    function ordinaryBuffer(buffer) {
      try { byteLength.call(buffer); return true; }
      catch (_) { return false; }
    }
    if (ArrayBuffer.isView(value)) {
      if (!ordinaryBuffer(value.buffer))
        throw TypeError('An ordinary byte buffer is required.');
      view = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    } else if (ordinaryBuffer(value)) {
      view = new Uint8Array(value);
    } else {
      throw TypeError('An ArrayBuffer or a byte view is required.');
    }
    return new Uint8Array(view); // Own the exact bytes before the first await.
  }

  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const rotate = (value, count) => (value >>> count) | (value << (32 - count));
  const hex = bytes => Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');

  function sha256Fallback(bytes) {
    const state = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const words = new Uint32Array(64);
    function block(input, offset) {
      for (let i = 0; i < 16; i++) {
        const at = offset + i * 4;
        words[i] = (input[at] << 24) | (input[at + 1] << 16) | (input[at + 2] << 8) | input[at + 3];
      }
      for (let i = 16; i < 64; i++) {
        const a = words[i - 15], b = words[i - 2];
        const low = rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3);
        const high = rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10);
        words[i] = (words[i - 16] + low + words[i - 7] + high) >>> 0;
      }
      let a = state[0], b = state[1], c = state[2], d = state[3];
      let e = state[4], f = state[5], g = state[6], h = state[7];
      for (let i = 0; i < 64; i++) {
        const sum = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
        const choose = (e & f) ^ (~e & g);
        const first = (h + sum + choose + K[i] + words[i]) >>> 0;
        const other = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (other + majority) >>> 0;
        h = g; g = f; f = e; e = (d + first) >>> 0;
        d = c; c = b; b = a; a = (first + second) >>> 0;
      }
      state[0] = (state[0] + a) >>> 0; state[1] = (state[1] + b) >>> 0;
      state[2] = (state[2] + c) >>> 0; state[3] = (state[3] + d) >>> 0;
      state[4] = (state[4] + e) >>> 0; state[5] = (state[5] + f) >>> 0;
      state[6] = (state[6] + g) >>> 0; state[7] = (state[7] + h) >>> 0;
    }
    let at = 0;
    for (; at + 64 <= bytes.length; at += 64) block(bytes, at);
    const remaining = bytes.length - at;
    const tail = new Uint8Array(remaining < 56 ? 64 : 128);
    tail.set(bytes.subarray(at)); tail[remaining] = 128;
    // SHA-256 encodes the original bit length as an unsigned 64-bit value.
    const low = (bytes.length * 8) >>> 0, high = Math.floor(bytes.length / 0x20000000) >>> 0;
    const end = tail.length;
    tail[end - 8] = high >>> 24; tail[end - 7] = high >>> 16;
    tail[end - 6] = high >>> 8; tail[end - 5] = high;
    tail[end - 4] = low >>> 24; tail[end - 3] = low >>> 16;
    tail[end - 2] = low >>> 8; tail[end - 1] = low;
    for (let offset = 0; offset < tail.length; offset += 64) block(tail, offset);
    return Array.from(state, value => value.toString(16).padStart(8, '0')).join('');
  }

  async function sha256Hex(value) {
    const bytes = byteSnapshot(value);
    try {
      const subtle = root.crypto && root.crypto.subtle;
      if (subtle && typeof subtle.digest === 'function') {
        const digest = byteSnapshot(await subtle.digest('SHA-256', bytes));
        if (digest.length === 32) return hex(digest);
      }
    } catch (_) { /* HTTP or disabled WebCrypto: use the same local algorithm. */ }
    return sha256Fallback(bytes);
  }

  return Object.freeze({uuid, sha256Hex});
});
