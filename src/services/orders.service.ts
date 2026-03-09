import { supabase } from '../db/supabase.js'
import type { Order, NewOrderItem } from '@billsplit/shared'
import { calculateSubtotal, calculateTax } from '@billsplit/shared'
import { TAX_RATES } from '@billsplit/shared'

function mapOrder(row: Record<string, unknown>): Order {
  return {
    ...(row as unknown as Order),
    items: (row.items as Order['items']) ?? [],
  }
}

export async function fetchOrders(status: 'open' | 'closed'): Promise<Order[]> {
  const { data, error } = await supabase
    .from('orders')
    .select('*, items:order_items(*)')
    .eq('status', status)
    .order(status === 'open' ? 'created_at' : 'updated_at', { ascending: false })
    .limit(status === 'closed' ? 100 : 1000)

  if (error) throw new Error(error.message)
  return (data ?? []).map(mapOrder)
}

export async function getOrderById(orderId: string): Promise<Order | null> {
  const { data, error } = await supabase
    .from('orders')
    .select('*, items:order_items(*)')
    .eq('id', orderId)
    .single()

  if (error || !data) return null
  return mapOrder(data)
}

export async function getOpenOrderForTable(tableId: string): Promise<Order | null> {
  const { data, error } = await supabase
    .from('orders')
    .select('*, items:order_items(*)')
    .eq('table_id', tableId)
    .eq('status', 'open')
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle()

  if (error || !data) return null
  return mapOrder(data)
}

export async function createOrder(
  tableId: string,
  tableNumber: number,
  items: NewOrderItem[],
): Promise<Order> {
  const subtotal = calculateSubtotal(
    items.map(i => ({ dish_price: i.dish_price, quantity: i.quantity })),
  )
  const tax_amount = calculateTax(subtotal, TAX_RATES.ES)
  const total = +(subtotal + tax_amount).toFixed(2)

  const { data: order, error: orderErr } = await supabase
    .from('orders')
    .insert({
      table_id: tableId,
      table_number: tableNumber,
      status: 'open',
      subtotal,
      tax_amount,
      total,
    })
    .select()
    .single()

  if (orderErr) throw new Error(orderErr.message)
  if (!order) throw new Error('Failed to create order')

  const { error: itemsErr } = await supabase
    .from('order_items')
    .insert(
      items.map(i => ({
        order_id: order.id,
        dish_name: i.dish_name,
        dish_price: i.dish_price,
        quantity: i.quantity,
        notes: i.notes ?? null,
        diner_name: i.diner_name ?? 'Cliente',
        kitchen_status: 'pending',
        payment_status: 'unassigned',
      })),
    )

  if (itemsErr) throw new Error(itemsErr.message)

  return { ...order, items: [] } as unknown as Order
}

export async function addItemsToOrder(orderId: string, items: NewOrderItem[]): Promise<void> {
  const { error } = await supabase
    .from('order_items')
    .insert(
      items.map(i => ({
        order_id: orderId,
        dish_name: i.dish_name,
        dish_price: i.dish_price,
        quantity: i.quantity,
        notes: i.notes ?? null,
        diner_name: i.diner_name ?? 'Cliente',
        kitchen_status: 'pending',
        payment_status: 'unassigned',
      })),
    )

  if (error) throw new Error(error.message)

  // Recalculate totals
  const existing = await getOrderById(orderId)
  if (existing) {
    const allItems = [
      ...existing.items.map(i => ({ dish_price: i.dish_price, quantity: i.quantity })),
    ]
    const subtotal = calculateSubtotal(allItems)
    const tax_amount = calculateTax(subtotal, TAX_RATES.ES)
    const total = +(subtotal + tax_amount).toFixed(2)

    await supabase
      .from('orders')
      .update({ subtotal, tax_amount, total, updated_at: new Date().toISOString() })
      .eq('id', orderId)
  }
}

export async function closeOrder(orderId: string): Promise<void> {
  const { error } = await supabase
    .from('orders')
    .update({ status: 'closed', updated_at: new Date().toISOString() })
    .eq('id', orderId)

  if (error) throw new Error(error.message)
}

export async function updateItemKitchenStatus(
  itemId: string,
  status: 'pending' | 'cooking' | 'ready' | 'delivered',
): Promise<void> {
  const { error } = await supabase
    .from('order_items')
    .update({ kitchen_status: status })
    .eq('id', itemId)

  if (error) throw new Error(error.message)
}

export async function updateItemsPaymentStatus(
  itemIds: string[],
  status: 'unassigned' | 'assigned' | 'paid',
): Promise<void> {
  const { error } = await supabase
    .from('order_items')
    .update({ payment_status: status })
    .in('id', itemIds)

  if (error) throw new Error(error.message)
}
