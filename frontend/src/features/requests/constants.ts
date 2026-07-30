/**
 * The request-type catalog offered by the Create Request form's type
 * selector. No backend method enumerates all active
 * `WorkflowDefinition`s across every type (`WorkflowDefinitionService
 * .list_versions` requires an already-known `request_type`) — this is a
 * frontend-only convenience list, provisional and requiring a manual
 * update whenever a new workflow definition is authored and activated.
 * Server-side validation (`422 VALIDATION_ERROR` if no active definition
 * exists for the submitted type) remains the real source of truth
 * regardless of what this list offers.
 */
export const REQUEST_TYPES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "leave_request", label: "Leave" },
  { value: "expense_reimbursement", label: "Expense Reimbursement" },
  { value: "purchase_order", label: "Purchase Order" },
  { value: "access_request", label: "Access" },
  { value: "hardware_request", label: "Hardware" },
  { value: "software_request", label: "Software" },
  { value: "travel_request", label: "Travel" },
  { value: "contract_request", label: "Contract" },
  { value: "recruitment_request", label: "Recruitment" },
];
