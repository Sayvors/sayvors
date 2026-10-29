/* Catalog API — the items the assistant quotes and the public share link. */

import { apiFetch } from "@/lib/api-rag";

export interface CatalogItem {
  id: string;
  name: string;
  description: string | null;
  sku: string | null;
  price: string | null;
  currency: string | null;
  price_display: string | null;
  image_url: string | null;
  item_url: string | null;
  in_stock: boolean;
  availability_note: string | null;
  active: boolean;
  sort_order: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CatalogItemInput {
  name: string;
  description?: string | null;
  sku?: string | null;
  price?: number | string | null;
  currency?: string | null;
  image_url?: string | null;
  item_url?: string | null;
  in_stock?: boolean;
  availability_note?: string | null;
  active?: boolean;
  sort_order?: number;
}

export async function listCatalogItems(
  includeInactive = true,
): Promise<{ items: CatalogItem[]; total: number }> {
  const data = await apiFetch(
    `/api/v1/catalog?include_inactive=${includeInactive ? "true" : "false"}`,
  );
  return { items: (data?.items ?? []) as CatalogItem[], total: data?.total ?? 0 };
}

export async function createCatalogItem(input: CatalogItemInput): Promise<CatalogItem> {
  return (await apiFetch("/api/v1/catalog", {
    method: "POST",
    body: JSON.stringify(input),
  })) as CatalogItem;
}

export async function updateCatalogItem(
  id: string,
  patch: Partial<CatalogItemInput>,
): Promise<CatalogItem> {
  return (await apiFetch(`/api/v1/catalog/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  })) as CatalogItem;
}

export async function deleteCatalogItem(id: string): Promise<void> {
  await apiFetch(`/api/v1/catalog/${id}`, { method: "DELETE" });
}

export interface CatalogShare {
  token: string | null;
  path: string | null;
}

export async function getCatalogShare(): Promise<CatalogShare> {
  return (await apiFetch("/api/v1/catalog/share")) as CatalogShare;
}

export async function createCatalogShare(rotate = false): Promise<CatalogShare> {
  return (await apiFetch(
    `/api/v1/catalog/share${rotate ? "?rotate=true" : ""}`,
    { method: "POST" },
  )) as CatalogShare;
}

export async function revokeCatalogShare(): Promise<void> {
  await apiFetch("/api/v1/catalog/share", { method: "DELETE" });
}

/* Public payload — no auth, no ids. */
export interface PublicCatalogItem {
  name: string;
  description: string | null;
  price_display: string | null;
  image_url: string | null;
  item_url: string | null;
  in_stock: boolean;
  availability_note: string | null;
}

export interface PublicCatalog {
  business_name: string;
  items: PublicCatalogItem[];
}
