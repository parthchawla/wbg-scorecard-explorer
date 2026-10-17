import { createContext, useContext } from "react";

export interface ChatApi { ask: (question: string) => void; open: boolean; setOpen: (v: boolean) => void }
export const ChatContext = createContext<ChatApi>({ ask: () => {}, open: false, setOpen: () => {} });
export const useChat = () => useContext(ChatContext);
