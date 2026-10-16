import React, { useState } from 'react'
import { SidebarRail } from '../sidebar/SidebarRail'
import { ConversationList } from '../sidebar/ConversationList'
import { ContactsView } from '../sidebar/ContactsView'
import { GroupsView } from '../sidebar/GroupsView'
import { ChatWindow } from '../chat/ChatWindow'

export const MainLayout: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<'chats' | 'contacts' | 'groups'>('chats')

  return (
    <div className="flex h-screen w-screen bg-slate-100 overflow-hidden font-sans">
      {/* 1. Leftmost slim icon rail */}
      <SidebarRail currentTab={currentTab} onTabChange={setCurrentTab} />

      {/* 2. Middle list panel */}
      {currentTab === 'chats' && <ConversationList />}
      {currentTab === 'contacts' && <ContactsView />}
      {currentTab === 'groups' && <GroupsView />}

      {/* 3. Main chat window */}
      <ChatWindow />
    </div>
  )
}
