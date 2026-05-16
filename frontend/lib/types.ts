/**
 * TypeScript mirrors of the Pydantic schemas in api/app/schemas/.
 *
 * Source of truth is the OpenAPI spec at /openapi.json — these are
 * hand-written for clarity (no codegen tool in the build) and must
 * stay in sync if the backend changes. Add a new field on the backend
 * → add it here and you'll get a compile error at every call site
 * that needs to think about it.
 *
 * Decimal fields come over the wire as JSON strings (Pydantic v2
 * serialises Decimal as string by default). We type them as `string`
 * rather than `number` so a `parseFloat` is explicit at the
 * formatting boundary rather than implied.
 */

// ----- Auth -----
export interface UserOut {
  id: number;
  email: string;
  full_name: string;
  is_admin: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

// ----- Catalog -----
export interface CategoryOut {
  id: number;
  name: string;
  slug: string;
  parent_id: number | null;
}

export interface VariantOut {
  id: number;
  sku: string;
  variant_name: string;
  price: string; // Decimal
  weight_grams: number | null;
}

export interface ProductOut {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  brand: string | null;
  base_price: string; // Decimal
  is_active: boolean;
  attributes: Record<string, unknown>;
  category: CategoryOut;
  variants: VariantOut[];
}

export interface ProductList {
  items: ProductOut[];
  total: number;
  page: number;
  page_size: number;
}

// ----- Search (Meilisearch) -----
export interface SearchHit {
  id: number;
  name: string;
  slug: string;
  brand: string | null;
  price: number; // float in the API response
  category_name: string;
  in_stock: boolean;
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
  took_ms: number;
  facets: Record<string, Record<string, number>>;
}

// ----- Cart -----
export interface CartItemOut {
  variant_id: number;
  sku: string;
  name: string;
  quantity: number;
  unit_price: string; // Decimal
  line_total: string; // Decimal
}

export interface CartOut {
  items: CartItemOut[];
  subtotal: string; // Decimal
  item_count: number;
}

// ----- Orders -----
export type OrderStatus =
  | "pending"
  | "paid"
  | "fulfilling"
  | "shipped"
  | "delivered"
  | "cancelled";

export type PaymentStatus =
  | "initiated"
  | "captured"
  | "failed"
  | "refunded";

export interface OrderItemOut {
  variant_id: number;
  quantity: number;
  unit_price: string;
  line_total: string;
}

export interface PaymentOut {
  amount: string;
  currency: string;
  status: PaymentStatus;
}

export interface OrderOut {
  id: number;
  status: OrderStatus;
  subtotal: string;
  shipping_fee: string;
  total: string;
  flash_sale_id: number | null;
  placed_at: string;
  items: OrderItemOut[];
  payment: PaymentOut | null;
}

export interface OrderList {
  items: OrderOut[];
  total: number;
  page: number;
  page_size: number;
}

// ----- Addresses -----
export interface AddressOut {
  id: number;
  label: string;
  line1: string;
  line2: string | null;
  city: string;
  postal_code: string;
  country: string;
  is_default: boolean;
}

// ----- Flash sales -----
export type FlashSaleStatus = "scheduled" | "active" | "ended" | "cancelled";

export interface FlashSaleItemOut {
  id: number;
  variant_id: number;
  sale_price: string;
  quantity_allocated: number;
  per_user_limit: number;
}

export interface FlashSaleOut {
  id: number;
  name: string;
  starts_at: string;
  ends_at: string;
  status: FlashSaleStatus;
  items: FlashSaleItemOut[];
}

// ----- Admin -----
export interface InventoryRow {
  variant_id: number;
  sku: string;
  product_id: number;
  product_name: string;
  variant_name: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  low_stock_threshold: number;
}

export interface InventoryList {
  items: InventoryRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface FlashSaleAnalytics {
  flash_sale_id: number;
  totals: Array<{ action: string; events: number; quantity: number }>;
  timeline: Array<{
    minute: string;
    action: string;
    events: number;
    quantity: number;
  }>;
  rejections: Array<{ rejection_reason: string; count: number }>;
  latency_ms: { p50: number; p95: number; p99: number; samples: number };
}

// ----- Errors -----
export class ApiError extends Error {
  status: number;
  retryAfter: number | null;
  body: unknown;

  constructor(status: number, message: string, body: unknown = null, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}
