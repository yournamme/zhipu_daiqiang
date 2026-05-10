import { createApp } from "vue";
import {
  create,
  NAlert,
  NButton,
  NButtonGroup,
  NCard,
  NConfigProvider,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NForm,
  NFormItem,
  NImage,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpin,
  NSwitch,
  NTable,
  NTag,
  NTooltip
} from "naive-ui";
import App from "./App.vue";
import "./styles.css";

const naive = create({
  components: [
    NAlert,
    NButton,
    NButtonGroup,
    NCard,
    NConfigProvider,
    NDrawer,
    NDrawerContent,
    NEmpty,
    NForm,
    NFormItem,
    NImage,
    NInput,
    NModal,
    NPopconfirm,
    NSelect,
    NSpin,
    NSwitch,
    NTable,
    NTag,
    NTooltip
  ]
});

createApp(App).use(naive).mount("#app");
