/**
 * The one place a react-hook-form field's validation error is rendered,
 * so every form in the app announces it to assistive technology the same
 * way: `role="alert"` makes a screen reader announce the message the
 * moment it appears, and `id` is what the field's own `<Input
 * aria-describedby={...}>` points back to.
 *
 * Usage:
 * ```tsx
 * <Label htmlFor="email">Email</Label>
 * <Input
 *   id="email"
 *   aria-invalid={!!errors.email}
 *   aria-describedby={errors.email ? "email-error" : undefined}
 *   {...register("email")}
 * />
 * <FormFieldError id="email-error" message={errors.email?.message} />
 * ```
 */
export function FormFieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}
