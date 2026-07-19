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
 * Keeps a stable visual container mounted before asynchronous feedback arrives.
 * Fluent MessageBar owns the single announcement path through useAnnounce.
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

  return <div data-feedback-region data-feedback-intent={intent}>{content}</div>;
}
