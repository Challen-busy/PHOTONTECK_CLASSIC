/**
 * CompanySwitcher —— 头部公司切换器（已接后端）
 *
 * 落 00b 页面4「公司切换器」+ 总览 §9.3「用户-公司-角色三元授权」+ 决策B（EXT-01-L）：
 *  - 候选公司 = /api/me 的 `companies`（= authorized_company_ids 对应的已开通公司简表）
 *  - 当前选中 = /api/me 的 `active_company_id`
 *  - 切换 = POST /api/me/switch-company → 后端重写会话 active_company_id 并回完整 user payload
 *    （后端 _company_filter 据此过滤；无 DB 写，只改签名 Cookie）
 *  - 切换成功后用返回 payload 刷新 AuthContext，并广播事件让台账/工作台重取
 *
 * 不再用 localStorage 占位：active_company_id 是会话权威，前端只反映、不自存。
 */

import { useState } from 'react';
import { Select, Tooltip, App } from 'antd';
import { BankOutlined } from '@ant-design/icons';
import { switchCompany } from '../api';
import { useAuth } from '../auth';

export default function CompanySwitcher() {
  const { user, setUser } = useAuth();
  const { message } = App.useApp();
  const [switching, setSwitching] = useState(false);

  const companies = user?.companies || [];
  const active = user?.active_company_id ?? user?.company_id ?? null;

  // 单一公司无需切换器（仍展示，作为当前归属指示）
  const options = companies.map((c) => ({
    value: c.id,
    label: c.short_name || c.name || c.code,
  }));

  const onChange = async (val) => {
    if (val === active) return;
    setSwitching(true);
    try {
      const { data } = await switchCompany(val);
      // 后端回完整 user payload（含新的 active_company_id）→ 刷新全局
      setUser(data);
      // 广播：让工作台/台账随 active_company_id 重取
      window.dispatchEvent(new CustomEvent('pt:company-changed', { detail: { companyId: val } }));
      const label = options.find((o) => o.value === val)?.label || val;
      message.success(`已切换到 ${label}`);
    } catch (e) {
      message.error(e.response?.data?.detail || '切换公司失败（可能未开通该公司）');
    } finally {
      setSwitching(false);
    }
  };

  return (
    <Tooltip title="切换当前操作公司（仅限已开通）" placement="bottom">
      <Select
        size="small"
        variant="filled"
        value={active}
        onChange={onChange}
        loading={switching}
        options={options}
        placeholder="选择公司"
        suffixIcon={<BankOutlined />}
        style={{ minWidth: 150 }}
        popupMatchSelectWidth={false}
        disabled={options.length <= 1}
      />
    </Tooltip>
  );
}
