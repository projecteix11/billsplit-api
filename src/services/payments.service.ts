import { createHmac } from 'node:crypto'
import forge from 'node-forge'
import { supabase } from '../db/supabase.js'
import type { PaymentMethod } from '@billsplit/shared'

const REDSYS_SECRET = process.env.REDSYS_SECRET ?? 'sq7HjrUOBfKmC576ILgskD900SqIlHkI8awNPoDg'
const REDSYS_MERCHANT_CODE = process.env.REDSYS_MERCHANT_CODE ?? '999008881'
const REDSYS_TERMINAL = process.env.REDSYS_TERMINAL ?? '001'
const REDSYS_URL = 'https://sis-t.redsys.es:25443/sis/realizarPago'

// ── Redsys signing ──────────────────────────────────────────────────────────

function deriveKey(secret: string, orderNumber: string): Uint8Array {
  const keyBinary = forge.util.decode64(secret).substring(0, 24)
  const l = Math.ceil(orderNumber.length / 8) * 8
  const padded = orderNumber.padEnd(l, '\0').substring(0, l)

  const iv = forge.util.createBuffer()
  for (let i = 0; i < 8; i++) iv.putByte(0)

  const cipher = forge.cipher.createCipher(
    '3DES-CBC',
    forge.util.createBuffer(keyBinary, 'raw'),
  )
  cipher.start({ iv })
  cipher.update(forge.util.createBuffer(padded, 'raw'))
  cipher.finish()

  const raw = cipher.output.getBytes().substring(0, l)
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}

export function signRedsys(amount: number, urlOk: string, urlKo: string) {
  const orderNumber = Date.now().toString().slice(-12)
  const amountCents = Math.round(amount * 100).toString()

  const params: Record<string, string> = {
    DS_MERCHANT_AMOUNT: amountCents,
    DS_MERCHANT_ORDER: orderNumber,
    DS_MERCHANT_MERCHANTCODE: REDSYS_MERCHANT_CODE,
    DS_MERCHANT_TERMINAL: REDSYS_TERMINAL,
    DS_MERCHANT_TRANSACTIONTYPE: '0',
    DS_MERCHANT_CURRENCY: '978',
    DS_MERCHANT_URLOK: urlOk,
    DS_MERCHANT_URLKO: urlKo,
  }

  const merchantParams = Buffer.from(JSON.stringify(params)).toString('base64')
  const derivedKey = deriveKey(REDSYS_SECRET, orderNumber)

  const hmac = createHmac('sha256', derivedKey)
  hmac.update(merchantParams)

  return {
    Ds_MerchantParameters: merchantParams,
    Ds_Signature: hmac.digest('base64'),
    Ds_SignatureVersion: 'HMAC_SHA256_V1',
    redsysUrl: REDSYS_URL,
    orderNumber,
  }
}

// ── Payment CRUD ────────────────────────────────────────────────────────────

export async function createPayment(
  orderId: string,
  amount: number,
  method: PaymentMethod,
) {
  const { data, error } = await supabase
    .from('payments')
    .insert({
      order_id: orderId,
      amount,
      tip_amount: 0,
      total_charged: amount,
      payment_method: method,
      status: 'confirmed',
    })
    .select()
    .single()

  if (error) throw new Error(error.message)
  return data
}
