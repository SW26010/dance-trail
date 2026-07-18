import {
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  type MessageBarProps,
} from "@fluentui/react-components";
import type { ReactNode } from "react";

type FeedbackRegionProps = {
  message?: ReactNode | null;
  title?: ReactNode;
  intent?: MessageBarProps["intent"];
};

/**
 * Keeps both ARIA live-region containers mounted before asynchronous feedback
 * arrives. Fluent MessageBar supplies the visual treatment inside the stable
 * container; only its content is inserted or cleared.
 */
export function FeedbackRegion({ message, title, intent = "info" }: FeedbackRegionProps) {
  const present = message !== null && message !== undefined;
  const assertive = intent === "error";
  const content = present ? (
    <MessageBar intent={intent} politeness={assertive ? "assertive" : "polite"}>
      <MessageBarBody>
        {title && <MessageBarTitle>{title}</MessageBarTitle>}
        {message}
      </MessageBarBody>
    </MessageBar>
  ) : null;

  return (
    <>
      <div role="status" aria-live="polite" aria-atomic="true" data-live-region="status">
        {!assertive ? content : null}
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true" data-live-region="alert">
        {assertive ? content : null}
      </div>
    </>
  );
}
