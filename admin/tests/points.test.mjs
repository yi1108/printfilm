import test from 'node:test'
import assert from 'node:assert/strict'
import { points, parsePoints } from '../src/lib/points.ts'
test('Stored integer credits display as Points without rescaling',()=>{ assert.match(points(10000), /10,000/); assert.match(points(25), /25/); assert.equal(points(undefined),'—'); assert.equal(points(1.2),'—') })
test('Point inputs preserve wire units and reject fractional or exponential values',()=>{ assert.equal(parsePoints('100'),100); assert.equal(parsePoints('0'),0); assert.equal(parsePoints('100000000',100000000),100000000); for(const value of ['', '1.5','1e2','-1','Infinity','9007199254740992']) assert.equal(parsePoints(value),null); assert.equal(parsePoints('100000001',100000000),null) })
