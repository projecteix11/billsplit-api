import { Hono } from 'hono'
import * as paymentsService from '../services/payments.service.js'

const app = new Hono()

app.post('/payments', async (c) => {
  const { orderId, amount, method } = await c.req.json()

  if (!orderId || !amount || !method) {
    return c.json({ error: 'orderId, amount and method are required' }, 400)
  }

  const payment = await paymentsService.createPayment(orderId, amount, method)
  return c.json({ data: payment, error: null }, 201)
})

app.post('/payments/redsys-sign', async (c) => {
  const { amount, urlOk, urlKo } = await c.req.json()

  if (!amount || !urlOk || !urlKo) {
    return c.json({ error: 'amount, urlOk and urlKo are required' }, 400)
  }

  const signed = paymentsService.signRedsys(amount, urlOk, urlKo)
  return c.json(signed)
})

export default app
