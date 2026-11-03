import { useRef } from "react";
import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { FilterSurface } from "../../patterns/FilterSurface";
import { PageHeader } from "../../patterns/PageHeader";
import { Pager } from "../../patterns/Pager";
import { AsyncBoundary, Button, EmptyState, RAIL_QUERY, SearchField } from "../../ui";
import { RailShell } from "../../patterns/RailShell";
import { NotificationFilters } from "./NotificationFilters";
import { NotificationRow } from "./NotificationRow";
import { PAGE_SIZE, useNotificationsController } from "./useNotificationsController";
import "./notification-screen.css";
import {
  notificationsNotificationScreenClearEveryFilterAndLens,
  notificationsNotificationScreenFindARoleCompanyOr,
  notificationsNotificationScreenLoadFailed,
  notificationsNotificationScreenLoading,
  notificationsNotificationScreenMarkAllRead,
  notificationsNotificationScreenNothingHereYet,
  notificationsNotificationScreenNothingUnread,
  notificationsNotificationScreenRefreshFailed,
  notificationsNotificationScreenResetAll,
  notificationsNotificationScreenScansNewRolesForYou,
  notificationsNotificationScreenSearchNotifications,
} from "../../copy/gen/notifications";
import { shellNavNotifications } from "../../copy/gen/shell";

export { PAGE_SIZE };

export function NotificationScreen() {
  const c = useNotificationsController();
  const {
    status, priority, categories, search, activeCount, narrowed, resetAll,
    list, retry, data, total, unread, offset, expanded, copied,
  } = c;

  // The register stands beside the list at rail widths and folds into the
  // toolbar's Filters panel below them — one home at a time (ui/FilterRail).
  const railMode = useMediaQuery(RAIL_QUERY);
  const root = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef: root, elementRef: toolbarRef, property: "--notif-toolbar-h" });

  const filters = (
    <NotificationFilters
      status={status}
      onStatusChange={c.setStatus}
      priority={priority}
      onPriorityChange={c.setPriority}
      categories={categories}
      onCategoriesChange={c.setCategories}
      counts={data?.category_counts}
    />
  );

  const content = (
    <div className="notif-content">
      <AsyncBoundary
        resource={{ ...list, retry }}
        loading={notificationsNotificationScreenLoading()}
        failed={notificationsNotificationScreenLoadFailed()}
        refreshFailed={notificationsNotificationScreenRefreshFailed()}
        isEmpty={(d) => d.items.length === 0}
        empty={
          <EmptyState title={notificationsNotificationScreenNothingHereYet({ choice: (narrowed) ? "yes" : "no" })}>
            {notificationsNotificationScreenScansNewRolesForYou({ choice: (narrowed) ? "yes" : "no" })}
          </EmptyState>
        }
      >
        {(d) => (
          <>
            <div className="notif-list">
              {d.items.map((n) => (
                <NotificationRow
                  key={n.id}
                  n={n}
                  isOpen={expanded.has(n.id)}
                  copied={copied}
                  onCopy={c.copy}
                  onOpen={c.openNotification}
                  onOpenJob={c.openJobFromNotification}
                  onToggle={c.toggleExpanded}
                  onMarkRead={c.markRead}
                  onDismiss={c.dismiss}
                  movedPage={c.movedPage}
                />
              ))}
            </div>
            <Pager total={total} pageSize={PAGE_SIZE} offset={offset} onOffsetChange={c.setOffset} />
          </>
        )}
      </AsyncBoundary>
    </div>
  );

  return (
    <main className="main notif-center" data-design-system="app" ref={root}>
      <PageHeader title={shellNavNotifications()} />

      {/* Search leads the screen it filters; the screen's one verb sits at
          the end. The Board's and the register's bar, on the shared sticky
          recipe (.app-toolbar, surfaces.css). */}
      <div className="notif-toolbar app-toolbar" data-selection="chrome" ref={toolbarRef}>
        <SearchField
          className="notif-search"
          label={notificationsNotificationScreenSearchNotifications()}
          placeholder={notificationsNotificationScreenFindARoleCompanyOr()}
          value={search}
          onChange={c.setSearch}
        />
        {/* The undo follows the search it sits beside; its scope is the same
            on both screens: every filter and lens, never the query.
            */}
        {activeCount > 0 && (
          <Button variant="link" className="ui-btn-quiet" onClick={resetAll} title={notificationsNotificationScreenClearEveryFilterAndLens()}>
            {notificationsNotificationScreenResetAll()}
          </Button>
        )}
        <div className="notif-toolbar-end">
          <FilterSurface railMode={railMode} activeCount={activeCount}>
            {filters}
          </FilterSurface>
          {/* The screen's one verb wears the toolbar rank (`ui-btn-strong`,
              the register's "Follow all"): full ink on a strong hairline, so
              it reads as the band's action rather than one more label in it,
              still a ghost, never the gold fill that means "commit". */}
          {/* Disabled, it says why where a reader can see it. */}
          {unread === 0 && (
            <span className="notif-toolbar-why" id="notif-markall-why">{notificationsNotificationScreenNothingUnread()}</span>
          )}
          <Button
            className="ui-btn-strong"
            onClick={c.markAll}
            disabled={unread === 0}
            aria-describedby={unread === 0 ? "notif-markall-why" : undefined}
          >
            {notificationsNotificationScreenMarkAllRead()}
          </Button>
        </div>
      </div>

      <RailShell railMode={railMode} register={filters} className="notif-shell">
        {content}
      </RailShell>
    </main>
  );
}
