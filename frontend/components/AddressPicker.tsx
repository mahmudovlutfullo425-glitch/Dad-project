"use client";

import type { AddressOut } from "@/lib/types";

interface AddressPickerProps {
  addresses: AddressOut[];
  value: number | null;
  onChange: (id: number) => void;
}

export function AddressPicker({ addresses, value, onChange }: AddressPickerProps) {
  if (addresses.length === 0) {
    return (
      <p className="text-sm text-red-600">
        No saved addresses on file. (Seed data ships 1–2 per user — run{" "}
        <code>make seed</code> if your account is fresh.)
      </p>
    );
  }
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-semibold text-slate-900">Ship to</legend>
      {addresses.map((a) => (
        <label
          key={a.id}
          className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
            value === a.id ? "border-brand bg-brand/5" : "border-slate-200"
          }`}
        >
          <input
            type="radio"
            name="address"
            value={a.id}
            checked={value === a.id}
            onChange={() => onChange(a.id)}
            className="mt-1"
          />
          <span className="text-sm">
            <span className="font-medium capitalize text-slate-900">
              {a.label}
              {a.is_default && (
                <span className="ml-2 text-xs text-brand">default</span>
              )}
            </span>
            <span className="block text-slate-600">{a.line1}</span>
            {a.line2 && <span className="block text-slate-600">{a.line2}</span>}
            <span className="block text-slate-600">
              {a.city}, {a.postal_code}, {a.country}
            </span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}
