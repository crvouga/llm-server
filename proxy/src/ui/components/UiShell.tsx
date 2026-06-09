/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import { chatStyles } from '../../chat/styles';
import { dashboardStyles } from '../../dashboard/styles';
import { UI_CLIENT_SCRIPT_PATH } from '../../shared/constants';
import { sharedStyles } from '../../shared/styles';

export const UiShell: FC = () => (
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>LLM Proxy</title>
      <style>{dashboardStyles}</style>
      <style>{chatStyles}</style>
      <style>{sharedStyles}</style>
    </head>
    <body>
      <div id="ui-root" />
      <script type="module" src={UI_CLIENT_SCRIPT_PATH} />
    </body>
  </html>
);
