import { useEffect } from "react";

type Owner = { value: string };
type Attribute = { original: string | null; owners: Owner[] };
const bodies = new WeakMap<HTMLElement, Map<string, Attribute>>();

/** Last mounted owner wins. Out-of-order cleanup never removes another
 * wearer's material; the last owner restores the pre-existing attribute. */
export function useBodyAttribute(name: string, value: string) {
  useEffect(() => {
    const body = document.body;
    let attributes = bodies.get(body);
    if (!attributes) {
      attributes = new Map();
      bodies.set(body, attributes);
    }
    let attribute = attributes.get(name);
    if (!attribute) {
      attribute = { original: body.getAttribute(name), owners: [] };
      attributes.set(name, attribute);
    }
    const owner = { value };
    attribute.owners.push(owner);
    body.setAttribute(name, value);

    return () => {
      const current = attribute.owners[attribute.owners.length - 1];
      attribute.owners.splice(attribute.owners.indexOf(owner), 1);
      if (current === owner && body.getAttribute(name) === value) {
        const restored = attribute.owners[attribute.owners.length - 1]?.value ?? attribute.original;
        if (restored === null) body.removeAttribute(name);
        else body.setAttribute(name, restored);
      }
      if (attribute.owners.length === 0) attributes.delete(name);
    };
  }, [name, value]);
}
