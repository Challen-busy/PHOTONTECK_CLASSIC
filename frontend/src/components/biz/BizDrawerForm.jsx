/**
 * BizDrawerForm —— 详情/录单抽屉标准壳（包 AntD Pro DrawerForm）
 *
 * 落 UX 律 14 §1 骨架四件套「详情抽屉（不跳页）」+ 红线④（禁 modal 套 modal，主录单走抽屉）：
 *  - 点台账行 → 右侧滑抽屉看/改，列表不消失、不跳页
 *  - 抽屉顶部放「当前能做的动作按钮」由调用方经 submitter / extra 注入
 *  - 提交建议走 引擎 预览→ChangeCard→commit（onFinish 里调用方接）
 *
 * 受控用法（配合 ProTable 行点击）：
 *   <BizDrawerForm open={open} onOpenChange={setOpen} title="销售订单 SO" onFinish={...}>
 *     <ProFormText name="..." /> ... <BizEditableTable .../>
 *   </BizDrawerForm>
 */

import { DrawerForm } from '@ant-design/pro-components';

export default function BizDrawerForm({
  open,
  onOpenChange,
  trigger,
  title,
  width = 720,
  onFinish,
  initialValues,
  submitter,
  drawerProps,
  children,
  ...rest
}) {
  return (
    <DrawerForm
      open={open}
      onOpenChange={onOpenChange}
      trigger={trigger}
      title={title}
      width={width}
      initialValues={initialValues}
      onFinish={onFinish}
      // 抽屉而非 modal 承载主录单流（红线④）；右滑、可点遮罩关
      drawerProps={{
        destroyOnHidden: true,
        maskClosable: false,
        ...drawerProps,
      }}
      // 提交按钮文案默认「保存」；调用方可换成 预览→确认卡 触发器
      submitter={
        submitter === false
          ? false
          : {
              searchConfig: { submitText: '保存', resetText: '取消' },
              ...submitter,
            }
      }
      {...rest}
    >
      {children}
    </DrawerForm>
  );
}
