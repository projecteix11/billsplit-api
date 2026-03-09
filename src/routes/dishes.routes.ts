import { Hono } from 'hono'
import { getDishes, getCategories } from '../services/dishes.service.js'

const app = new Hono()

app.get('/dishes', async (c) => {
  const dishes = await getDishes()
  return c.json({ data: dishes, error: null })
})

app.get('/categories', async (c) => {
  const categories = await getCategories()
  return c.json({ data: categories, error: null })
})

export default app
