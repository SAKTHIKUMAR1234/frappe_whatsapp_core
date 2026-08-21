import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync(new URL('./frappeLogin.js', import.meta.url), 'utf8')

assert.match(source, /\/login\?redirect-to=/)
assert.match(source, /encodeURIComponent\(target\)/)
assert.doesNotMatch(source, /password|\/api\/method\/login/)

console.log('frappe login redirect tests passed')
