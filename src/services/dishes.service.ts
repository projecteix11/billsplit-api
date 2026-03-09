import { supabase } from '../db/supabase.js'
import type { Dish, DishCategory } from '@billsplit/shared'

export async function getDishes(): Promise<Dish[]> {
  const { data, error } = await supabase
    .from('dishes')
    .select('*')
    .eq('is_available', true)
    .order('name')

  if (error) throw new Error(error.message)
  return (data ?? []) as Dish[]
}

export async function getCategories(): Promise<DishCategory[]> {
  const { data, error } = await supabase
    .from('dish_categories')
    .select('*')
    .order('sort_order')

  if (error) throw new Error(error.message)
  return (data ?? []) as DishCategory[]
}
