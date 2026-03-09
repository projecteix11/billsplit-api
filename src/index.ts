import { serve } from '@hono/node-server'
import { Hono } from 'hono'
import { corsMiddleware } from './middleware/cors.js'
import dishesRoutes from './routes/dishes.routes.js'
import ordersRoutes from './routes/orders.routes.js'
import orderItemsRoutes from './routes/order-items.routes.js'
import paymentsRoutes from './routes/payments.routes.js'

const app = new Hono()

// Global middleware
app.use('*', corsMiddleware)

// Health check
app.get('/api/health', (c) => c.json({ status: 'ok' }))

// Routes
app.route('/api', dishesRoutes)
app.route('/api', ordersRoutes)
app.route('/api', orderItemsRoutes)
app.route('/api', paymentsRoutes)

// Global error handler
app.onError((err, c) => {
  console.error('[api] Unhandled error:', err.message)
  return c.json({ data: null, error: err.message }, 500)
})

const port = Number(process.env.PORT ?? 3001)

console.log(`BillSplit API running on http://localhost:${port}`)
serve({ fetch: app.fetch, port })
