import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App.jsx';
import './index.css';

// dayjs 插件 — antd v6 DatePicker 必需
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import customParseFormat from 'dayjs/plugin/customParseFormat';
import advancedFormat from 'dayjs/plugin/advancedFormat';
import weekday from 'dayjs/plugin/weekday';
import localeData from 'dayjs/plugin/localeData';
import weekOfYear from 'dayjs/plugin/weekOfYear';
import weekYear from 'dayjs/plugin/weekYear';
import isBetween from 'dayjs/plugin/isBetween';
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter';
import isSameOrBefore from 'dayjs/plugin/isSameOrBefore';
dayjs.extend(customParseFormat);
dayjs.extend(advancedFormat);
dayjs.extend(weekday);
dayjs.extend(localeData);
dayjs.extend(weekOfYear);
dayjs.extend(weekYear);
dayjs.extend(isBetween);
dayjs.extend(isSameOrAfter);
dayjs.extend(isSameOrBefore);
dayjs.locale('zh-cn');

/* ============================================================
 * ElevenLabs-inspired theme —— 近白画布 + 纯黑主色 + 暖石点缀
 * 与 index.css 里的 --pt-* 变量保持语义一致
 * ============================================================ */
const theme = {
  token: {
    // color
    colorPrimary:       '#000000',
    colorInfo:          '#1f5aa8',
    colorSuccess:       '#1f8f3a',
    colorWarning:       '#b8860b',
    colorError:         '#b42318',
    colorLink:          '#000000',
    colorLinkHover:     '#4e4e4e',

    colorBgBase:        '#ffffff',
    colorBgLayout:      '#ffffff',
    colorBgContainer:   '#ffffff',
    colorBgElevated:    '#ffffff',

    colorText:          '#000000',
    colorTextSecondary: '#4e4e4e',
    colorTextTertiary:  '#777169',
    colorTextQuaternary:'#bfbbb5',

    colorBorder:          '#e5e5e5',
    colorBorderSecondary: 'rgba(0, 0, 0, 0.05)',

    // type
    fontFamily:
      '"Inter", -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 14,

    // radius —— 统一向 ElevenLabs 的 16–24 靠
    borderRadius:   12,
    borderRadiusXS: 4,
    borderRadiusSM: 8,
    borderRadiusLG: 16,

    // motion
    motionDurationMid:  '0.15s',
    motionDurationFast: '0.1s',

    // focus ring —— 柔和蓝
    controlOutline:      'rgba(147, 197, 253, 0.4)',
    controlOutlineWidth: 3,

    // box shadow —— 默认下拉/Popover 用的阴影
    boxShadow:
      'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 4px 8px',
    boxShadowSecondary:
      'rgba(0,0,0,0.04) 0px 2px 4px, rgba(0,0,0,0.06) 0px 0px 0px 1px',

    // wire frame
    wireframe: false,
  },
  components: {
    Layout: {
      siderBg:      '#ffffff',
      headerBg:     '#ffffff',
      bodyBg:       '#ffffff',
      headerHeight: 56,
      headerPadding:'0 24px',
      triggerBg:    '#ffffff',
      triggerColor: '#4e4e4e',
    },
    Menu: {
      itemBg:              'transparent',
      itemColor:           '#4e4e4e',
      itemHoverBg:         'rgba(0, 0, 0, 0.03)',
      itemHoverColor:      '#000000',
      itemSelectedBg:      '#f5f2ef',
      itemSelectedColor:   '#000000',
      itemBorderRadius:    8,
      itemMarginInline:    8,
      itemHeight:          40,
      fontSize:            14,
      iconSize:            16,
    },
    Button: {
      borderRadius:     9999,
      borderRadiusSM:   9999,
      borderRadiusLG:   9999,
      controlHeight:    36,
      controlHeightSM:  28,
      controlHeightLG:  44,
      fontWeight:       500,
      primaryShadow:    'rgba(0,0,0,0.04) 0px 4px 4px',
      defaultShadow:    'rgba(0,0,0,0.04) 0px 1px 2px',
      paddingInline:    18,
      paddingInlineSM:  14,
      paddingInlineLG:  22,
    },
    Card: {
      borderRadiusLG: 16,
      headerBg:       'transparent',
      headerFontSize: 16,
      paddingLG:      20,
    },
    Input: {
      borderRadius:   10,
      borderRadiusSM: 8,
      borderRadiusLG: 12,
      controlHeight:  36,
      paddingInline:  12,
      activeShadow:   'rgba(147, 197, 253, 0.4) 0px 0px 0px 3px',
    },
    Select: {
      borderRadius:   10,
      borderRadiusSM: 8,
      controlHeight:  36,
    },
    DatePicker: {
      borderRadius:  10,
      controlHeight: 36,
    },
    InputNumber: {
      borderRadius:  10,
      controlHeight: 36,
    },
    Tag: {
      borderRadiusSM: 4,
      defaultBg:      '#f5f2ef',
      defaultColor:   '#4e4e4e',
      fontSize:       12,
    },
    Table: {
      borderColor:         'rgba(0, 0, 0, 0.05)',
      headerBg:             '#f5f5f5',
      headerColor:          '#4e4e4e',
      headerSortActiveBg:   '#ece7e1',
      headerSortHoverBg:    '#ece7e1',
      rowHoverBg:           'rgba(0, 0, 0, 0.03)',
      cellPaddingBlock:     12,
      cellPaddingBlockSM:   8,
      cellFontSize:         13,
      cellFontSizeSM:       13,
      borderRadius:         12,
    },
    Drawer: {
      borderRadiusLG: 16,
      paddingLG:      20,
    },
    Modal: {
      borderRadiusLG: 16,
      paddingLG:      20,
    },
    Tabs: {
      itemSelectedColor: '#000000',
      itemHoverColor:    '#000000',
      itemColor:         '#4e4e4e',
      inkBarColor:       '#000000',
      titleFontSize:     14,
      horizontalItemGutter: 24,
    },
    Badge: {
      colorBgContainer: '#000000',
    },
    Timeline: {
      tailColor: 'rgba(0, 0, 0, 0.08)',
    },
    Dropdown: {
      borderRadiusLG: 12,
      paddingBlock:   6,
    },
    Segmented: {
      borderRadius:   9999,
      borderRadiusSM: 9999,
      itemSelectedBg: '#ffffff',
      itemColor:      '#4e4e4e',
      itemHoverColor: '#000000',
      trackBg:        '#f5f5f5',
    },
  },
};

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ConfigProvider locale={zhCN} theme={theme}>
        {/* antd v6 App 容器：提供 message/notification/Modal 的 context，
            使 App.useApp() 可用、消除"静态方法无法消费 ConfigProvider context"告警 */}
        <AntdApp>
          <App />
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  </React.StrictMode>
);
