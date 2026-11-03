import { Button, Icon } from "../ui";
import {
  sharedPagerNext,
  sharedPagerPageOf,
  sharedPagerPrev,
} from "../copy/gen/shared";
import { Msg } from "../ui/Msg";

/** Offset state (including reconciliation after a count shrinks) stays with its query. */
export function Pager({ total, pageSize, offset, onOffsetChange }: {
  total: number;
  pageSize: number;
  offset: number;
  onOffsetChange: (offset: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.floor(offset / pageSize) + 1;
  if (pages <= 1) return null;

  const changePage = (nextOffset: number) =>
    onOffsetChange(Math.max(0, Math.min(nextOffset, (pages - 1) * pageSize)));

  return (
    <div className="pager" data-selection="chrome">
      <Button size="sm" disabled={page <= 1} onClick={() => changePage(offset - pageSize)}>
        <Icon name="arrowLeft" size={14} /> {sharedPagerPrev()}
      </Button>
      <span><Msg of={sharedPagerPageOf} elems={{ page: page, pages: pages }} /></span>
      <Button size="sm" disabled={page >= pages} onClick={() => changePage(offset + pageSize)}>
        {sharedPagerNext()} <Icon name="arrowRight" size={14} />
      </Button>
    </div>
  );
}
