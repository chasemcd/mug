/*
 * canonicalize.js -- RFC 8785 (JSON Canonicalization Scheme) reference
 * canonicalizer, vendored for the MUG Phase 0 cross-language conformance suite.
 *
 * Derived from the "canonicalize" reference implementation
 * (https://github.com/cyberphone/json-canonicalization by Anders Rundgren, and
 * the npm "canonicalize" package). Distributed under the MIT License.
 *
 * The MIT License (MIT)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
(function (global) {
  'use strict';

  function canonicalize(object) {
    if (typeof object === 'number' && isNaN(object)) {
      throw new Error('Cannot serialize NaN');
    }
    if (object === Infinity || object === -Infinity) {
      throw new Error('Cannot serialize Infinity');
    }
    if (object === null || typeof object !== 'object') {
      // Primitives (including numbers) go through JSON.stringify, which uses the
      // ECMAScript Number-to-String algorithm that RFC 8785 adopts as its
      // number basis.
      return JSON.stringify(object);
    }
    if (object.toJSON instanceof Function) {
      return canonicalize(object.toJSON());
    }
    if (Array.isArray(object)) {
      var acc = '';
      for (var i = 0; i < object.length; i++) {
        var element = object[i];
        if (element === undefined || typeof element === 'symbol') {
          element = null;
        }
        acc += (i === 0 ? '' : ',') + canonicalize(element);
      }
      return '[' + acc + ']';
    }
    // RFC 8785 orders object members by the UTF-16 code units of their keys,
    // which is exactly what Array.prototype.sort() (default lexicographic
    // comparison) produces.
    var keys = Object.keys(object).sort();
    var out = '';
    for (var k = 0; k < keys.length; k++) {
      var key = keys[k];
      var value = object[key];
      if (value === undefined || typeof value === 'symbol') {
        continue;
      }
      out += (out.length === 0 ? '' : ',') +
        JSON.stringify(key) + ':' + canonicalize(value);
    }
    return '{' + out + '}';
  }

  global.canonicalize = canonicalize;
})(typeof self !== 'undefined' ? self : this);
