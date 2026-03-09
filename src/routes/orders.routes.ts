import { Hono } from 'hono'
import { authMiddleware } from '../middleware/auth.js'
import * as ordersService from '../services/orders.service.js'

const app = new Hono()

// ── Public routes (client) ──────────────────────────────────────────────────

app.post('/orders', async (c) => {
  const { tableId, tableNumber, items } = await c.req.json()

  if (!tableId || !tableNumber || !Array.isArray(items) || items.length === 0) {
    return c.json({ error: 'tableId, tableNumber and items[] are required' }, 400)
  }

  const order = await ordersService.createOrder(tableId, tableNumber, items)
  return c.json({ data: order, error: null }, 201)
})

app.get('/orders/:orderId', async (c) => {
  const order = await ordersService.getOrderById(c.req.param('orderId'))
  if (!order) return c.json({ error: 'Order not found' }, 404)
  return c.json({ data: order, error: null })
})

app.post('/orders/:orderId/items', async (c) => {
  const { items } = await c.req.json()

  if (!Array.isArray(items) || items.length === 0) {
    return c.json({ error: 'items[] is required' }, 400)
  }

  await ordersService.addItemsToOrder(c.req.param('orderId'), items)
  return c.json({ data: null, error: null })
})

app.patch('/orders/:orderId/close', async (c) => {
  await ordersService.closeOrder(c.req.param('orderId'))
  return c.json({ data: null, error: null })
})

app.get('/tables/:tableId/open-order', async (c) => {
  const order = await ordersService.getOpenOrderForTable(c.req.param('tableId'))
  if (!order) return c.json({ error: 'No open order for this table' }, 404)
  return c.json({ data: order, error: null })
})

// ── Protected routes (management) ───────────────────────────────────────────

app.get('/orders', authMiddleware, async (c) => {
  const status = (c.req.query('status') ?? 'open') as 'open' | 'closed'
  const orders = await ordersService.fetchOrders(status)
  return c.json({ data: orders, error: null })
})

export default app
