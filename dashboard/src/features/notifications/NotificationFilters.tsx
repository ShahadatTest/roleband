import { FacetGroup, FilterGroup, FilterRegister, Segmented } from "../../ui";
import {
  NOTIF_MEMORY_SCOPE, ROLE_CATEGORIES, SYNC_CATEGORIES, facetEntries, splitCategories,
} from "./filters";
import type { NotificationPriority, NotificationStatus } from "./filters";
import {
  notificationsNotificationFiltersAll,
  notificationsNotificationFiltersFilterByRoleEvent,
  notificationsNotificationFiltersFilterByScanEvent,
  notificationsNotificationFiltersHigh,
  notificationsNotificationFiltersPriority,
  notificationsNotificationFiltersPriority2,
  notificationsNotificationFiltersReadStatus,
  notificationsNotificationFiltersRoles,
  notificationsNotificationFiltersScans,
  notificationsNotificationFiltersStatus,
  notificationsNotificationFiltersUnread,
} from "../../copy/gen/notifications";

/** The notifications register: two lens switches and the category facets, in
 *  whichever home the screen gives it (the rail, or FilterSurface's modal).
 *  It carries no head row — the undo lives in the toolbar's count line, so
 *  nothing here shifts when a filter goes active (the Board's rule). */
export function NotificationFilters({
  status,
  onStatusChange,
  priority,
  onPriorityChange,
  categories,
  onCategoriesChange,
  counts,
}: {
  status: NotificationStatus;
  onStatusChange: (next: NotificationStatus) => void;
  priority: NotificationPriority;
  onPriorityChange: (next: NotificationPriority) => void;
  categories: string[];
  onCategoriesChange: (next: string[]) => void;
  counts: Record<string, number> | undefined;
}) {
  const { sync: syncSelected, role: roleSelected } = splitCategories(categories);
  return (
    <FilterRegister scope={NOTIF_MEMORY_SCOPE} className="notif-filters">
      <FilterGroup title={notificationsNotificationFiltersStatus()}>
        <Segmented
          className="notif-status"
          label={notificationsNotificationFiltersReadStatus()}
          value={status}
          onChange={onStatusChange}
          options={[
            { value: "all", label: notificationsNotificationFiltersAll() },
            { value: "unread", label: notificationsNotificationFiltersUnread() },
          ]}
        />
      </FilterGroup>
      <FilterGroup title={notificationsNotificationFiltersPriority()}>
        <Segmented
          className="notif-priority"
          label={notificationsNotificationFiltersPriority2()}
          value={priority}
          onChange={onPriorityChange}
          options={[
            { value: "", label: notificationsNotificationFiltersAll() },
            { value: "high", label: notificationsNotificationFiltersHigh() },
          ]}
        />
      </FilterGroup>
      <FacetGroup
        title={notificationsNotificationFiltersScans()}
        ariaLabel={notificationsNotificationFiltersFilterByScanEvent()}
        entries={facetEntries(SYNC_CATEGORIES, counts)}
        selected={syncSelected}
        onChange={(next) => onCategoriesChange([...next, ...roleSelected])}
      />
      <FacetGroup
        title={notificationsNotificationFiltersRoles()}
        ariaLabel={notificationsNotificationFiltersFilterByRoleEvent()}
        entries={facetEntries(ROLE_CATEGORIES, counts)}
        selected={roleSelected}
        onChange={(next) => onCategoriesChange([...syncSelected, ...next])}
      />
    </FilterRegister>
  );
}
